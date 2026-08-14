"""Unit tests for ReportValidator assertions and safety invariants."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from faultline.diagnostics import ScenarioRepository
from faultline.gemini import FakeGeminiProvider
from faultline.models import (
    AdvantageDimension,
    ConflictType,
    EvaluatedHypothesis,
    EvidenceStrengthBand,
    FaultReport,
    HypothesisDraft,
    HypothesisDraftSet,
    InvalidModelOutputError,
    LifecycleState,
    ObservationEvidenceScore,
    PolicyConfig,
    RootCauseCode,
)
from faultline.orchestrator import IncidentOrchestrator, OrchestratorError
from faultline.reasoning import PolicyEngine, StrategyRanker
from faultline.validation import ReportValidator, ValidationError


def test_validator_passes_canonical_result() -> None:
    """Validator accepts a correctly formed canonical analysis result."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    validator = ReportValidator()
    assert validator.validate(result) is True


def test_validator_rejects_insufficient_source_groups() -> None:
    """Validator rejects report with fewer than 2 independent source groups."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: filter evidence to single source group
    result.evidence = [obs for obs in result.evidence if obs.source_group.value == "telemetry"]

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Insufficient independent diagnostic sources"):
        validator.validate(result)


def test_validator_rejects_hallucinated_evidence_id_in_conflicts() -> None:
    """Validator rejects report if conflict references an unissued evidence ID."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: inject fake evidence ID
    result.conflicts[0].evidence_ids.append("EV-999")

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Conflict evidence citations mismatch|non-existent evidence ID"):
        validator.validate(result)


def test_validator_rejects_modified_ranking_order() -> None:
    """Validator detects if strategy ranking was tampered with or disagrees with Python calculation."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: swap rank 1 and rank 2
    temp = result.strategy_ranking[0]
    result.strategy_ranking[0] = result.strategy_ranking[1]
    result.strategy_ranking[1] = temp

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Strategy ranking mismatch"):
        validator.validate(result)


def test_validator_rejects_unapproved_execution_status() -> None:
    """Validator rejects any report attempting to claim execution succeeded autonomously."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    result.execution.execution_status = "executed"

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Safety boundary violated"):
        validator.validate(result)


def test_validator_rejects_mismatched_execution_command() -> None:
    """Validator rejects a report where suggested_command does not match the winning strategy."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: set suggested_command to an arbitrary or incorrect command
    result.execution.suggested_command = "kubectl delete pod --all"

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Execution command mismatch|Execution suggested_command mismatch"):
        validator.validate(result)


def test_validator_rejects_hallucinated_alien_contradiction_analysis() -> None:
    """Validator rejects ungrounded contradiction claims (e.g., 'Aliens caused the outage' or conflict denial)."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: inject hallucinated alien explanation
    result.recommendation.grounded_contradiction_analysis = (
        "Aliens attacked the datacenter and caused all servers to fail simultaneously with cosmic rays."
    )

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="not semantically grounded|denial of verified diagnostic conflicts|does not reference any affected components"):
        validator.validate(result)


def test_validator_rejects_ungrounded_summary() -> None:
    """Validator rejects executive summaries that fail to reference the winning repair action."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: replace executive summary with generic ungrounded text
    result.recommendation.executive_summary = (
        "The investigation has finished and some unknown repairs might be necessary soon."
    )

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Executive summary lacks grounding"):
        validator.validate(result)


def test_orchestrator_rejects_fabricated_model_citation() -> None:
    """Orchestrator immediately catches and rejects fabricated EV-999 citations from model."""

    class MaliciousModelProvider(FakeGeminiProvider):
        def synthesise_hypotheses(
            self,
            incident: FaultReport,
            evidence_ledger: list,
            allowed_causes: list,
            session: object = None,
        ) -> HypothesisDraftSet:
            return HypothesisDraftSet(
                hypotheses=[
                    HypothesisDraft(
                        cause_code=RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
                        summary="Forged citation test",
                        causal_chain=["Forged step 1", "Forged step 2"],
                        supporting_evidence_ids=["EV-999"],  # Non-existent ID
                        opposing_evidence_ids=[],
                    ),
                    HypothesisDraft(
                        cause_code=RootCauseCode.TRAFFIC_SURGE,
                        summary="Secondary cause",
                        causal_chain=["Step 1", "Step 2"],
                        supporting_evidence_ids=["EV-001"],
                        opposing_evidence_ids=[],
                    ),
                ]
            )

    orchestrator = IncidentOrchestrator(provider=MaliciousModelProvider())
    with pytest.raises(
        (OrchestratorError, InvalidModelOutputError)
    ):
        orchestrator.analyze_scenario("cache_invalidation_lag")


def test_model_shortlist_variation_preserves_deterministic_winner() -> None:
    """Verifies that differing candidate shortlists cannot change the winning repair strategy."""

    class SubsetModelProvider(FakeGeminiProvider):
        def synthesise_hypotheses(
            self,
            incident: FaultReport,
            evidence_ledger: list,
            allowed_causes: list,
            session: object = None,
        ) -> HypothesisDraftSet:
            # Model shortlists only 2 causes with valid citations
            queue_ids = [obs.id for obs in evidence_ledger if obs.component.value == "message_queue"]
            db_workload_ids = [
                obs.id for obs in evidence_ledger if obs.component.value == "database" and obs.scope == "workload"
            ]
            db_probe_ids = [
                obs.id
                for obs in evidence_ledger
                if obs.component.value == "database" and obs.scope == "synthetic_probe"
            ]

            return HypothesisDraftSet(
                hypotheses=[
                    HypothesisDraft(
                        cause_code=RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
                        summary="Consumer stalled",
                        causal_chain=["Step A", "Step B"],
                        supporting_evidence_ids=queue_ids,
                        opposing_evidence_ids=[],
                    ),
                    HypothesisDraft(
                        cause_code=RootCauseCode.DATABASE_CAPACITY_DEGRADATION,
                        summary="DB degradation",
                        causal_chain=["Step B", "Step C"],
                        supporting_evidence_ids=db_workload_ids,
                        opposing_evidence_ids=db_probe_ids,
                    ),
                ]
            )

    orchestrator = IncidentOrchestrator(provider=SubsetModelProvider())
    result = orchestrator.analyze_scenario("cache_invalidation_lag")
    assert result.strategy_ranking[0].strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
    assert result.strategy_ranking[0].rank == 1


def test_orchestrator_investigation_trace_includes_final_validation_step() -> None:
    """Verifies that the returned result includes the final validation action in its investigation trace."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    assert len(result.investigation_trace) > 0
    final_event = result.investigation_trace[-1]
    assert final_event.action_type == "validation"
    assert "passed all strict validation" in final_event.summary


def test_strategy_ranker_unrounded_precision_sorting() -> None:
    """StrategyRanker strictly sorts by exact unrounded float values before rounding for display."""
    policy = PolicyEngine()
    ranker = StrategyRanker(policy)

    hyp = EvaluatedHypothesis(
        cause_code=RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
        name="Cache Invalidation Consumer Stalled",
        summary="Test cause",
        causal_chain=["Step 1", "Step 2"],
        supporting_observations=[],
        opposing_observations=[],
        supporting_score=14.0,
        opposing_score=0.0,
        net_evidence_score=14.0,
        decision_weight=100.0,
        strength_band=EvidenceStrengthBand.STRONG,
        unresolved_uncertainties=[],
    )

    ranked = ranker.rank_strategies([hyp])
    assert len(ranked) >= 4
    # Ensure rank numbers are sequential and strictly ordered
    for idx, strat in enumerate(ranked, start=1):
        assert strat.rank == idx
    assert ranked[0].strategy_id == "RECOVER_CONSUMER_AND_DRAIN"


def test_precision_tiebreaker_ranks_higher_unrounded_score_over_lexicographical_id() -> None:
    """When two strategies round to the same display score (e.g. 2.500 vs 2.504),
    the strategy with the higher unrounded score strictly ranks first, even if its ID
    is lexicographically later."""
    policy = PolicyEngine()
    ranker = StrategyRanker(policy)

    # Custom strategy weights: ZZZ strategy has 2.504 / 0.60 and AAA strategy has 2.500 / 0.60
    policy.strategies = {
        "AAA_LOWER": {
            "name": "Strategy AAA (2.500)",
            "description": "Lower precision strategy",
            "effectiveness_by_cause": {"CACHE_INVALIDATION_CONSUMER_STALLED": 2.500 / 0.60},
            "safety": 0.0,
            "speed": 0.0,
            "affordability": 0.0,
            "risk_notes": "None",
            "reversibility": "High",
            "suggested_command": "echo aaa",
            "preconditions": [],
        },
        "ZZZ_HIGHER": {
            "name": "Strategy ZZZ (2.504)",
            "description": "Higher precision strategy",
            "effectiveness_by_cause": {"CACHE_INVALIDATION_CONSUMER_STALLED": 2.504 / 0.60},
            "safety": 0.0,
            "speed": 0.0,
            "affordability": 0.0,
            "risk_notes": "None",
            "reversibility": "High",
            "suggested_command": "echo zzz",
            "preconditions": [],
        },
    }

    hyp = EvaluatedHypothesis(
        cause_code=RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
        name="Test",
        summary="Test",
        causal_chain=["Step 1"],
        supporting_observations=[],
        opposing_observations=[],
        supporting_score=10.0,
        opposing_score=0.0,
        net_evidence_score=10.0,
        decision_weight=100.0,
        strength_band=EvidenceStrengthBand.STRONG,
        unresolved_uncertainties=[],
    )

    ranked = ranker.rank_strategies([hyp])
    assert len(ranked) == 2
    assert ranked[0].strategy_id == "ZZZ_HIGHER"
    assert ranked[0].rank == 1
    assert ranked[1].strategy_id == "AAA_LOWER"
    assert ranked[1].rank == 2
    # Check that both round to 2.50 for two decimal display
    assert round(ranked[0].final_score, 2) == 2.50
    assert round(ranked[1].final_score, 2) == 2.50


def test_validator_rejects_inverted_supporting_opposing_citation() -> None:
    """Validator rejects hypothesis citing an opposing metric as supporting."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Invert an observation in hypothesis
    healthy_db_ping = next(
        obs for obs in result.evidence if obs.signal == "db_synthetic_direct_probe" and obs.status.value == "healthy"
    )
    inverted_score = ObservationEvidenceScore(
        evidence_id=healthy_db_ping.id,
        source_group=healthy_db_ping.source_group,
        component=healthy_db_ping.component,
        signal=healthy_db_ping.signal,
        reliability_score=1,
        freshness_score=1,
        directness_score=1,
        total_strength=1,
        relationship="supports",
    )
    result.hypotheses[0].supporting_observations.append(inverted_score)

    validator = ReportValidator()
    with pytest.raises(ValidationError, match=r"reports unexpected supporting evidence|policy defines it as (opposes|unrelated)|supporting observations count mismatch"):
        validator.validate(result)


def test_validator_rejects_false_advantage_claim_in_grounding() -> None:
    """Validator rejects structured grounding claiming safety advantage when alternative has lower safety."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    assert result.recommendation.grounding is not None
    # Tamper grounding to claim safety advantage when alternative has lower safety than winner
    result.recommendation.grounding.alternative_advantage_dimension = AdvantageDimension.SAFETY

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="claims safety advantage .* but winner has equal or higher"):
        validator.validate(result)


def test_validator_rejects_fabricated_hypothesis_scores_and_winner_override() -> None:
    """Validator rejects report where hypothesis scores and winning strategy were manipulated."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Adversarial tampering: inflate top hypothesis score to 100.0
    assert len(result.hypotheses) > 0
    result.hypotheses[0].net_evidence_score = 100.0

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="mismatch: reported 100.0, expected authoritative score"):
        validator.validate(result)


def test_validator_rejects_corrupted_grounding_reconciled_ids() -> None:
    """Validator rejects report when structured grounding contains fabricated conflict IDs."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    result.recommendation.grounding.reconciled_conflict_ids = ["CONF-FABRICATED-999"]
    validator = ReportValidator()
    with pytest.raises(ValidationError, match="reconciled conflicts mismatch"):
        validator.validate(result)


def test_validator_rejects_corrupted_grounding_top_cause() -> None:
    """Validator rejects report when structured grounding top cause code disagrees with authoritative evaluation."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    result.recommendation.grounding.top_cause_code = RootCauseCode.TRAFFIC_SURGE
    validator = ReportValidator()
    with pytest.raises(ValidationError, match="top cause code mismatch"):
        validator.validate(result)


def test_orchestrator_discards_draft_with_empty_citations() -> None:
    """Orchestrator discards drafts that provide zero supporting citations, preserving remaining valid drafts."""

    class PartialEmptyCitationProvider(FakeGeminiProvider):
        def synthesise_hypotheses(self, incident, evidence_ledger, allowed_causes, session=None):
            return HypothesisDraftSet(
                hypotheses=[
                    HypothesisDraft(
                        cause_code=RootCauseCode.DATABASE_CAPACITY_DEGRADATION,
                        summary="Gremlins degraded the database.",
                        causal_chain=["Gremlins invaded", "DB slowed down"],
                        supporting_evidence_ids=[],  # Empty citations -> discarded
                        opposing_evidence_ids=[],
                        unresolved_uncertainties=[],
                    ),
                    HypothesisDraft(
                        cause_code=RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
                        summary="Consumer worker stalled.",
                        causal_chain=["Worker crashed", "Queue piled up"],
                        supporting_evidence_ids=["EV-002", "EV-007"],  # Valid citations (cache hit ratio + queue backlog)
                        opposing_evidence_ids=[],
                        unresolved_uncertainties=[],
                    ),
                    HypothesisDraft(
                        cause_code=RootCauseCode.TRAFFIC_SURGE,
                        summary="Traffic surge from outer space.",
                        causal_chain=["Aliens clicked refresh"],
                        supporting_evidence_ids=["EV-001"],  # Valid citation
                        opposing_evidence_ids=[],
                        unresolved_uncertainties=[],
                    ),
                ]
            )

    orchestrator = IncidentOrchestrator(provider=PartialEmptyCitationProvider())
    result = orchestrator.analyze_scenario("cache_invalidation_lag")
    # Verify report is still validated and gremlin draft summary was discarded
    assert result.validation_passed is True
    assert not any("Gremlins" in h.summary for h in result.hypotheses)


def test_error_sanitizer_redacts_private_keys_and_paths() -> None:
    """Error sanitizer strictly redacts secrets, private paths, and classifies into safe categories."""
    from faultline.gemini import sanitize_error_category

    err = RuntimeError("503 upstream service unavailable; api_key=SUPER-SECRET-KEY-12345; path=/srv/private/keys.env")
    sanitized = sanitize_error_category(err)
    assert "SUPER-SECRET-KEY" not in sanitized
    assert "/srv/private" not in sanitized
    assert sanitized == "service_unavailable (RuntimeError)"

    rate_err = Exception("429 rate limit exceeded for key AKIA-SECRET-999")
    sanitized_rate = sanitize_error_category(rate_err)
    assert "AKIA-SECRET" not in sanitized_rate
    assert sanitized_rate == "rate_limit_exceeded (Exception)"


def test_scenario_path_traversal_protection() -> None:
    """ScenarioRepository raises ValueError on path traversal attempts."""
    repo = ScenarioRepository()
    with pytest.raises(ValueError, match="Invalid scenario ID format"):
        repo.get_scenario("../policy")


def test_ledger_observation_immutability() -> None:
    """EvidenceObservation is frozen; attempts to mutate fields raise ValidationError."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    obs = result.evidence[0]
    with pytest.raises(PydanticValidationError):
        obs.id = "EV-999"  # type: ignore[misc]


def test_validator_rejects_non_contiguous_evidence_ids() -> None:
    """Validator rejects report with non-contiguous evidence IDs (e.g. EV-001, EV-003)."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: remove EV-002 so ledger is EV-001, EV-003...
    result.evidence = [obs for obs in result.evidence if obs.id != "EV-002"]

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Evidence ledger integrity violation"):
        validator.validate(result)


def test_validator_rejects_tampered_conflicts() -> None:
    """Validator recomputes conflicts from reconstructed ledger and rejects fabricated/tampered conflict lists."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: alter conflict type of the detected scope tension to direct contradiction
    result.conflicts[0].conflict_type = ConflictType.DIRECT_CONTRADICTION

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Conflict type mismatch on CONF-001"):
        validator.validate(result)


def test_validator_rejects_tampered_observation_score_breakdown() -> None:
    """Validator asserts exact match of every ObservationEvidenceScore component."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: inflate reliability score of first supporting observation in top hypothesis
    result.hypotheses[0].supporting_observations[0].reliability_score += 10

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Observation breakdown score mismatch"):
        validator.validate(result)


def test_validator_rejects_fewer_than_two_hypotheses() -> None:
    """Validator rejects report containing fewer than 2 hypotheses."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: truncate hypotheses to 1 (fewer than 2)
    result.hypotheses = result.hypotheses[:1]
    validator = ReportValidator()
    with pytest.raises(ValidationError, match="must contain at least 2 evaluated hypotheses"):
        validator.validate(result)

    # Tamper: truncate hypotheses to 0
    result.hypotheses = []
    with pytest.raises(ValidationError, match="must contain at least 2 evaluated hypotheses"):
        validator.validate(result)


def test_validator_rejects_omitted_breakdown_observation() -> None:
    """Validator rejects report if any authoritative observation is omitted from hypothesis breakdown."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: remove 1 supporting observation from top hypothesis
    assert len(result.hypotheses[0].supporting_observations) > 1
    result.hypotheses[0].supporting_observations = result.hypotheses[0].supporting_observations[:-1]

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="supporting observations count mismatch"):
        validator.validate(result)


def test_state_machine_transition_trace_from_to_states() -> None:
    """Trace items for state transitions accurately capture distinct from_state and to_state."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    state_transitions = [
        item for item in result.investigation_trace
        if item.action_type == "state_change" and "from_state" in item.details
    ]
    assert len(state_transitions) >= 5

    for trans in state_transitions:
        from_st = trans.details["from_state"]
        to_st = trans.details["to_state"]
        assert from_st != to_st, f"State change trace recorded identical from and to state: {from_st} -> {to_st}"


def test_validator_rejects_hallucinated_referenced_conflict_id() -> None:
    """Validator rejects StructuredDecisionGrounding referencing a non-existent conflict ID."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    assert result.recommendation.grounding is not None
    result.recommendation.grounding.referenced_conflict_ids = ["CONF-999"]

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="references non-existent conflict ID"):
        validator.validate(result)


def test_validator_rejects_hallucinated_referenced_evidence_id() -> None:
    """Validator rejects StructuredDecisionGrounding referencing a non-existent evidence ID."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    assert result.recommendation.grounding is not None
    result.recommendation.grounding.referenced_evidence_ids = ["EV-999"]

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="references non-existent evidence ID"):
        validator.validate(result)


def test_tool_deduplication_accounting_in_trace() -> None:
    """Investigation trace logs records_returned, records_appended, and records_deduplicated for all tool executions."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    tool_traces = [item for item in result.investigation_trace if item.action_type == "tool_result"]
    assert len(tool_traces) >= 2
    for tt in tool_traces:
        assert "records_returned" in tt.details
        assert "records_appended" in tt.details
        assert "records_deduplicated" in tt.details
        assert tt.details["records_returned"] >= tt.details["records_appended"]


def test_validator_rejects_causal_evidence_as_contextual() -> None:
    """Validator rejects hypothesis when direct causal evidence is improperly cited in contextual_evidence_ids."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Get a verified supporting observation for the top hypothesis
    causal_id = result.hypotheses[0].supporting_observations[0].evidence_id
    # Tamper: add causal_id to contextual_evidence_ids of top hypothesis
    result.hypotheses[0].contextual_evidence_ids = [causal_id]

    validator = ReportValidator()
    with pytest.raises(ValidationError, match=f"cites causal evidence '{causal_id}' as contextual"):
        validator.validate(result)


def test_validator_rejects_empty_model_conflict_references_when_conflicts_exist() -> None:
    """Validator rejects StructuredDecisionGrounding when referenced_conflict_ids is empty despite conflicts existing."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    assert result.conflicts
    assert result.recommendation.grounding is not None
    result.recommendation.grounding.referenced_conflict_ids = []

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="must reference at least one genuine conflict"):
        validator.validate(result)


def test_policy_config_rejects_incomplete_cause_catalogue() -> None:
    """PolicyConfig rejects catalogues missing any RootCauseCode."""
    policy = PolicyEngine()
    data = dict(policy.policy_data)
    data["cause_catalogue"] = dict(policy.cause_catalogue)
    # Remove one cause code
    del data["cause_catalogue"]["REPLICA_LAG"]

    with pytest.raises(ValueError, match="cause_catalogue must contain full catalogue"):
        PolicyConfig.model_validate(data)


def test_policy_config_rejects_negative_weights() -> None:
    """PolicyConfig rejects negative weights in reliability_weights or freshness_weights."""
    policy = PolicyEngine()
    data = dict(policy.policy_data)
    data["reliability_weights"] = dict(policy.reliability_weights)
    data["reliability_weights"]["verified"] = -5

    with pytest.raises(ValueError, match="reliability_weight 'verified' must be non-negative"):
        PolicyConfig.model_validate(data)


def test_orchestrator_validating_to_validated_state_transition() -> None:
    """IncidentOrchestrator properly transitions state from VALIDATING to VALIDATED via state machine."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    assert result.state == LifecycleState.VALIDATED
    state_traces = [item for item in result.investigation_trace if item.action_type == "state_change"]
    # Check that VALIDATING and VALIDATED are both recorded in trace
    states_logged = [st.details.get("to_state") for st in state_traces]
    assert LifecycleState.VALIDATING.value in states_logged
    assert LifecycleState.VALIDATED.value in states_logged


