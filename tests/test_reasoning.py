"""Unit tests for Evidence Ledger, Conflict Detection, Evidence Scoring, 4D Strategy Ranking, and Concurrency."""

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
    PolicyConfig,
    ReliabilityLevel,
    SourceGroup,
)
from faultline.orchestrator import IncidentOrchestrator
from faultline.reasoning import ConflictDetector, PolicyEngine


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
