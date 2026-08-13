"""Unit tests for ReportValidator assertions and safety invariants."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from faultline.diagnostics import ScenarioRepository
from faultline.gemini import FakeGeminiProvider
from faultline.models import (
    EvaluatedHypothesis,
    EvidenceStrengthBand,
    FaultReport,
    HypothesisDraft,
    HypothesisDraftSet,
    ObservationEvidenceScore,
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
    with pytest.raises(ValidationError, match="non-existent evidence ID"):
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
    with pytest.raises(ValidationError, match="not semantically grounded|denial of verified diagnostic conflicts"):
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
        OrchestratorError, match="Ungrounded or invalid evidence citations|Fabricated evidence citations"
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
    with pytest.raises(ValidationError, match=r"policy defines it as (opposes|unrelated)"):
        validator.validate(result)


def test_validator_rejects_false_advantage_claim_in_grounding() -> None:
    """Validator rejects structured grounding claiming safety advantage when alternative has lower safety."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    assert result.recommendation.grounding is not None
    # Tamper grounding to claim safety advantage when alternative has lower safety than winner
    result.recommendation.grounding.alternative_advantage_dimension = "safety"

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="claims safety advantage .* but winner has equal or higher"):
        validator.validate(result)


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
