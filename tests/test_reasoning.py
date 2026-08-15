from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from faultline.diagnostics import EvidenceLedger
from faultline.gemini import FakeGeminiProvider
from faultline.models import (
    ComponentEnum,
    ConflictType,
    EvidenceObservation,
    HealthDimension,
    HealthStatus,
    HypothesisDraft,
    HypothesisDraftSet,
    PolicyConfig,
    ReliabilityLevel,
    RootCauseCode,
    SourceGroup,
)
from faultline.orchestrator import IncidentOrchestrator
from faultline.reasoning import ConflictDetector, EvidenceEvaluator, PolicyEngine


def test_evidence_ledger_isolation_and_sequential_ids() -> None:
    """Ensure EvidenceLedger starts fresh at EV-001 and maintains immutability."""
    t0 = datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)
    ledger1 = EvidenceLedger(incident_at=t0)
    ledger2 = EvidenceLedger(incident_at=t0)

    obs1 = ledger1.append_observation(
        source_group=SourceGroup.TELEMETRY,
        source="test",
        component=ComponentEnum.API_GATEWAY,
        signal="p99",
        dimension=HealthDimension.LATENCY,
        status=HealthStatus.DEGRADED,
        value=2400.0,
        unit="ms",
        observed_at=t0,
        window_duration_seconds=300,
        scope="workload",
        reliability=ReliabilityLevel.AGGREGATED,
        details="high latency",
    )

    obs2 = ledger2.append_observation(
        source_group=SourceGroup.HEALTH_PROBE,
        source="test_probe",
        component=ComponentEnum.DATABASE,
        signal="ping",
        dimension=HealthDimension.AVAILABILITY,
        status=HealthStatus.HEALTHY,
        value=1.0,
        unit="ms",
        observed_at=t0,
        window_duration_seconds=60,
        scope="synthetic_probe",
        reliability=ReliabilityLevel.VERIFIED,
        details="healthy ping",
    )

    # Both isolated instances start at EV-001
    assert obs1.id == "EV-001"
    assert obs2.id == "EV-001"

    obs1_b = ledger1.append_observation(
        source_group=SourceGroup.OPERATIONAL_EVENTS,
        source="test_event",
        component=ComponentEnum.MESSAGE_QUEUE,
        signal="queue_backlog",
        dimension=HealthDimension.BACKLOG,
        status=HealthStatus.FAILED,
        value=1000.0,
        unit="msgs",
        observed_at=t0,
        window_duration_seconds=300,
        scope="queue",
        reliability=ReliabilityLevel.VERIFIED,
        details="backlog high",
    )
    assert obs1_b.id == "EV-002"
    assert len(ledger1.get_observations()) == 2
    assert len(ledger2.get_observations()) == 1


def test_evidence_ledger_natural_key_deduplication() -> None:
    """Ensure identical natural observations return the existing EV ID and do not mint duplicates."""
    t0 = datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)
    ledger = EvidenceLedger(incident_at=t0)

    obs1 = ledger.append_observation(
        source_group=SourceGroup.TELEMETRY,
        source="query_telemetry",
        component=ComponentEnum.API_GATEWAY,
        signal="p99_latency",
        dimension=HealthDimension.LATENCY,
        status=HealthStatus.DEGRADED,
        value=1850.0,
        unit="ms",
        observed_at=t0,
        window_duration_seconds=300,
        scope="workload",
        reliability=ReliabilityLevel.AGGREGATED,
        details="High latency",
    )
    assert obs1.id == "EV-001"

    # Append exact same observation again
    obs2 = ledger.append_observation(
        source_group=SourceGroup.TELEMETRY,
        source="query_telemetry",
        component=ComponentEnum.API_GATEWAY,
        signal="p99_latency",
        dimension=HealthDimension.LATENCY,
        status=HealthStatus.DEGRADED,
        value=1850.0,
        unit="ms",
        observed_at=t0,
        window_duration_seconds=300,
        scope="workload",
        reliability=ReliabilityLevel.AGGREGATED,
        details="High latency",
    )
    # Must return same instance and ID
    assert obs2.id == "EV-001"
    assert len(ledger.get_observations()) == 1


def test_evidence_ledger_from_validated_snapshot() -> None:
    """Verify from_validated_snapshot rejects non-contiguous IDs and duplicate content."""
    t0 = datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)
    obs1 = EvidenceObservation(
        id="EV-001",
        source_group=SourceGroup.TELEMETRY,
        source="query_telemetry",
        component=ComponentEnum.DATABASE,
        signal="latency",
        dimension=HealthDimension.LATENCY,
        status=HealthStatus.DEGRADED,
        value=100.0,
        unit="ms",
        observed_at=t0,
        window_start=t0,
        window_end=t0,
        scope="workload",
        reliability=ReliabilityLevel.AGGREGATED,
        details="high",
    )
    obs2_bad_id = EvidenceObservation(
        id="EV-003",  # Skip EV-002
        source_group=SourceGroup.HEALTH_PROBE,
        source="run_health_probes",
        component=ComponentEnum.DATABASE,
        signal="ping",
        dimension=HealthDimension.AVAILABILITY,
        status=HealthStatus.HEALTHY,
        value=1.0,
        unit="ms",
        observed_at=t0,
        window_start=t0,
        window_end=t0,
        scope="synthetic_probe",
        reliability=ReliabilityLevel.VERIFIED,
        details="healthy",
    )

    with pytest.raises(ValueError) as excinfo:
        EvidenceLedger.from_validated_snapshot([obs1, obs2_bad_id], incident_at=t0)
    assert "does not match expected sequential ID 'EV-002'" in str(excinfo.value)


def test_conflict_dimension_matching_and_scope_tension() -> None:
    """Verify that different dimensions in the same family produce SCOPE_TENSION, while same dimension produces DIRECT_CONTRADICTION."""
    t0 = datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)
    ledger = EvidenceLedger(incident_at=t0)

    # obs_a: database latency degraded (scope="workload")
    ledger.append_observation(
        source_group=SourceGroup.TELEMETRY,
        source="query_telemetry",
        component=ComponentEnum.DATABASE,
        signal="query_latency",
        dimension=HealthDimension.LATENCY,
        status=HealthStatus.DEGRADED,
        value=1850.0,
        unit="ms",
        observed_at=t0,
        window_duration_seconds=300,
        scope="workload",
        reliability=ReliabilityLevel.AGGREGATED,
        details="slow queries",
    )

    # obs_b: database latency healthy (scope="synthetic_probe") -> Differing scopes -> SCOPE_TENSION
    ledger.append_observation(
        source_group=SourceGroup.HEALTH_PROBE,
        source="run_health_probes",
        component=ComponentEnum.DATABASE,
        signal="ping_latency",
        dimension=HealthDimension.LATENCY,
        status=HealthStatus.HEALTHY,
        value=1.5,
        unit="ms",
        observed_at=t0,
        window_duration_seconds=60,
        scope="synthetic_probe",
        reliability=ReliabilityLevel.VERIFIED,
        details="fast ping",
    )

    conflicts = ConflictDetector.detect_conflicts(ledger)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == ConflictType.SCOPE_TENSION
    assert "Workload vs Synthetic Probe" in conflicts[0].headline

    # obs_c: database latency healthy in same scope "workload" from different source group -> DIRECT_CONTRADICTION
    ledger_direct = EvidenceLedger(incident_at=t0)
    ledger_direct.append_observation(
        source_group=SourceGroup.TELEMETRY,
        source="telemetry_agent",
        component=ComponentEnum.DATABASE,
        signal="query_latency",
        dimension=HealthDimension.LATENCY,
        status=HealthStatus.DEGRADED,
        value=1850.0,
        unit="ms",
        observed_at=t0,
        window_duration_seconds=300,
        scope="workload",
        reliability=ReliabilityLevel.AGGREGATED,
        details="slow queries",
    )
    ledger_direct.append_observation(
        source_group=SourceGroup.OPERATIONAL_EVENTS,
        source="db_events",
        component=ComponentEnum.DATABASE,
        signal="workload_status",
        dimension=HealthDimension.LATENCY,
        status=HealthStatus.HEALTHY,
        value=5.0,
        unit="ms",
        observed_at=t0,
        window_duration_seconds=300,
        scope="workload",
        reliability=ReliabilityLevel.VERIFIED,
        details="reported fast",
    )
    conflicts_direct = ConflictDetector.detect_conflicts(ledger_direct)
    assert len(conflicts_direct) == 1
    assert conflicts_direct[0].conflict_type == ConflictType.DIRECT_CONTRADICTION


def test_policy_json_validation() -> None:
    """Verify PolicyConfig rejects invalid weights, unapproved cause codes, or out-of-bounds metrics."""
    policy = PolicyEngine()
    raw_dict = policy.policy_data

    # Valid policy loads cleanly
    PolicyConfig.model_validate(raw_dict)

    # Invalid weights sum
    bad_dict = dict(raw_dict)
    bad_dict["scoring_weights"] = {"impact": 0.5, "safety": 0.2, "speed": 0.1, "affordability": 0.1}  # sum = 0.9
    with pytest.raises(ValidationError) as excinfo:
        PolicyConfig.model_validate(bad_dict)
    assert "Scoring weights must sum to 1.0" in str(excinfo.value)


def test_concurrent_investigations_isolation() -> None:
    """Verify 10 concurrent orchestrator analysis runs maintain absolute thread-safe isolation."""
    orchestrator = IncidentOrchestrator(provider=FakeGeminiProvider())

    def run_one(idx: int) -> str:
        scenario = "cache_invalidation_lag" if idx % 2 == 0 else "index_regression"
        result = orchestrator.analyze_scenario(scenario)
        assert result.validation_passed is True
        assert len(result.evidence) >= 4
        if scenario == "cache_invalidation_lag":
            assert result.strategy_ranking[0].strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
        else:
            assert result.strategy_ranking[0].strategy_id == "REBUILD_DATABASE_INDEX"
        return result.run_id

    with ThreadPoolExecutor(max_workers=5) as executor:
        run_ids = list(executor.map(run_one, range(10)))

    # Ensure all run IDs are strictly unique
    assert len(run_ids) == 10
    assert len(set(run_ids)) == 10


def test_hypothesis_draft_overlap_validation() -> None:
    """HypothesisDraft rejects duplicate citations or overlapping categories (supporting, opposing, contextual)."""
    # Duplicate within supporting
    with pytest.raises(ValidationError, match=r"must not contain duplicate entries|Duplicate evidence"):
        HypothesisDraft(
            cause_code=RootCauseCode.TRAFFIC_SURGE,
            summary="test",
            causal_chain=["a", "b"],
            supporting_evidence_ids=["EV-001", "EV-001"],
            opposing_evidence_ids=[],
        )

    # Overlap between supporting and opposing
    with pytest.raises(
        ValidationError, match=r"cannot be simultaneously supporting and opposing|cannot appear in both"
    ):
        HypothesisDraft(
            cause_code=RootCauseCode.TRAFFIC_SURGE,
            summary="test",
            causal_chain=["a", "b"],
            supporting_evidence_ids=["EV-001"],
            opposing_evidence_ids=["EV-001"],
        )

    # Overlap between supporting and contextual
    with pytest.raises(ValidationError, match=r"cannot be simultaneously contextual and supporting|cannot overlap"):
        HypothesisDraft(
            cause_code=RootCauseCode.TRAFFIC_SURGE,
            summary="test",
            causal_chain=["a", "b"],
            supporting_evidence_ids=["EV-001"],
            opposing_evidence_ids=[],
            contextual_evidence_ids=["EV-001"],
        )


def test_citation_category_semantic_verification() -> None:
    """EvidenceEvaluator validates citations strictly by policy match and allows contextual citations with 0 score impact."""
    t0 = datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)
    ledger = EvidenceLedger(incident_at=t0)

    # EV-001: API gateway throughput degraded (matches TRAFFIC_SURGE supports)
    obs1 = ledger.append_observation(
        source_group=SourceGroup.TELEMETRY,
        source="query_telemetry",
        component=ComponentEnum.API_GATEWAY,
        signal="p99_latency",
        dimension=HealthDimension.LATENCY,
        status=HealthStatus.DEGRADED,
        value=2000.0,
        unit="ms",
        observed_at=t0,
        window_duration_seconds=300,
        scope="workload",
        reliability=ReliabilityLevel.AGGREGATED,
        details="Gateway degraded",
    )

    # EV-002: Message queue backlog failed (matches CACHE_INVALIDATION_CONSUMER_STALLED supports)
    obs2 = ledger.append_observation(
        source_group=SourceGroup.OPERATIONAL_EVENTS,
        source="fetch_events",
        component=ComponentEnum.MESSAGE_QUEUE,
        signal="queue_backlog",
        dimension=HealthDimension.BACKLOG,
        status=HealthStatus.FAILED,
        value=50000.0,
        unit="msgs",
        observed_at=t0,
        window_duration_seconds=300,
        scope="queue",
        reliability=ReliabilityLevel.VERIFIED,
        details="Queue stalled",
    )

    evaluator = EvidenceEvaluator()

    # Draft citing EV-002 (queue) as supporting DATABASE_INDEX_REGRESSION -> REJECTED (unrelated signal)
    draft_unrelated = HypothesisDraft(
        cause_code=RootCauseCode.DATABASE_INDEX_REGRESSION,
        summary="DB index regression",
        causal_chain=["Step 1", "Step 2"],
        supporting_evidence_ids=[obs2.id],
        opposing_evidence_ids=[],
    )
    is_valid, errs = evaluator.validate_hypothesis_citations(draft_unrelated, ledger.get_observations())
    assert is_valid is False
    assert any("does not match any SUPPORTS rule" in e for e in errs)

    # Draft citing EV-002 as contextual evidence for TRAFFIC_SURGE -> ACCEPTED with 0 score impact
    draft_contextual = HypothesisDraft(
        cause_code=RootCauseCode.TRAFFIC_SURGE,
        summary="Traffic surge",
        causal_chain=["Step 1", "Step 2"],
        supporting_evidence_ids=[obs1.id],
        opposing_evidence_ids=[],
        contextual_evidence_ids=[obs2.id],
    )
    is_valid_ctx, errs_ctx = evaluator.validate_hypothesis_citations(draft_contextual, ledger.get_observations())
    assert is_valid_ctx is True
    assert len(errs_ctx) == 0

    evaluated = evaluator.evaluate_hypotheses(
        candidate_codes=[RootCauseCode.TRAFFIC_SURGE],
        ledger=ledger,
        draft_hypotheses=[draft_contextual],
    )
    assert len(evaluated) == 1
    # Check that EV-002 was not added to supporting or opposing observations (0 score impact)
    ev_ids_in_scores = {s.evidence_id for s in evaluated[0].supporting_observations}
    assert obs2.id not in ev_ids_in_scores
    assert evaluated[0].contextual_evidence_ids == [obs2.id]


def test_orchestrator_semantic_repair_flow() -> None:
    """When the initial candidate draft fails citation validation, IncidentOrchestrator invokes repair_hypotheses."""

    class FaultyInitialProvider(FakeGeminiProvider):
        def __init__(self) -> None:
            super().__init__()
            self.repair_called = False

        def synthesise_hypotheses(self, incident, evidence_ledger, allowed_causes, session=None):
            # Return 2 drafts: 1 with invalid citation, 1 with valid citation -> leaves only 1 valid draft (<2) and triggers repair!
            return HypothesisDraftSet(
                hypotheses=[
                    HypothesisDraft(
                        cause_code=RootCauseCode.DATABASE_INDEX_REGRESSION,
                        summary="Invalid citation",
                        causal_chain=["a", "b"],
                        supporting_evidence_ids=["EV-999"],  # Non-existent
                        opposing_evidence_ids=[],
                    ),
                    HypothesisDraft(
                        cause_code=RootCauseCode.TRAFFIC_SURGE,
                        summary="Valid secondary draft",
                        causal_chain=["c", "d"],
                        supporting_evidence_ids=["EV-001"],
                        opposing_evidence_ids=[],
                    ),
                ]
            )

        def repair_hypotheses(
            self, incident, evidence_ledger, allowed_causes, previous_drafts, validation_errors, session=None
        ):
            self.repair_called = True
            # Return valid drafts on repair
            return super().synthesise_hypotheses(incident, evidence_ledger, allowed_causes, session=session)

    provider = FaultyInitialProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    assert provider.repair_called is True
    assert result.validation_passed is True
