"""Unit tests for Phase 2: Evidence Ledger, Conflict Detection, Evidence Scoring, and 4D Strategy Ranking."""

from datetime import datetime, timezone

from faultline.diagnostics import DiagnosticService, EvidenceLedger, ScenarioRepository
from faultline.models import (
    ConflictType,
    EvidenceStrengthBand,
    HealthDimension,
    HealthStatus,
    ReliabilityLevel,
    RootCauseCode,
    SourceGroup,
)
from faultline.reasoning import ConflictDetector, EvidenceEvaluator, PolicyEngine, StrategyRanker


def test_evidence_ledger_isolation_and_sequential_ids() -> None:
    """Ensure EvidenceLedger starts fresh at EV-001 and maintains immutability."""
    t0 = datetime(2026, 8, 13, 10, 0, 0, tzinfo=timezone.utc)
    ledger1 = EvidenceLedger(incident_at=t0)
    ledger2 = EvidenceLedger(incident_at=t0)

    obs1 = ledger1.append_observation(
        source_group=SourceGroup.TELEMETRY,
        source="test",
        component="api_gateway",
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
        component="database",
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
        component="message_queue",
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


def test_canonical_scenario_diagnostic_collection() -> None:
    """Test executing all 3 diagnostic adapters against canonical scenario."""
    repo = ScenarioRepository()
    scenario = repo.get_scenario("cache_invalidation_lag")
    t0 = datetime.fromisoformat(scenario["incident_at"].replace("Z", "+00:00"))
    ledger = EvidenceLedger(incident_at=t0)
    service = DiagnosticService(scenario, ledger)

    res_telem = service.query_telemetry()
    assert res_telem["observations_count"] == 3
    assert len(ledger.get_by_source_group(SourceGroup.TELEMETRY)) == 3

    res_probe = service.run_health_probes()
    assert res_probe["observations_count"] == 3
    assert len(ledger.get_by_source_group(SourceGroup.HEALTH_PROBE)) == 3

    res_events = service.fetch_operational_events()
    assert res_events["observations_count"] == 3
    assert len(ledger.get_by_source_group(SourceGroup.OPERATIONAL_EVENTS)) == 3

    assert len(ledger.get_observations()) == 9
    assert ledger.successful_source_groups == {
        SourceGroup.TELEMETRY,
        SourceGroup.HEALTH_PROBE,
        SourceGroup.OPERATIONAL_EVENTS,
    }


def test_conflict_detection_classifies_scope_tension() -> None:
    """Test that DB workload degradation vs healthy synthetic probe is classified as SCOPE_TENSION."""
    repo = ScenarioRepository()
    scenario = repo.get_scenario("cache_invalidation_lag")
    t0 = datetime.fromisoformat(scenario["incident_at"].replace("Z", "+00:00"))
    ledger = EvidenceLedger(incident_at=t0)
    service = DiagnosticService(scenario, ledger)

    service.query_telemetry()
    service.run_health_probes()

    conflicts = ConflictDetector.detect_conflicts(ledger)
    assert len(conflicts) >= 1

    db_conflicts = [c for c in conflicts if c.component == "database"]
    assert len(db_conflicts) >= 1
    assert db_conflicts[0].conflict_type == ConflictType.SCOPE_TENSION
    assert "Workload vs Synthetic Probe" in db_conflicts[0].headline


def test_evidence_scoring_with_source_group_cap() -> None:
    """Test calculation of observation strength, source-group cap, and net evidence scores."""
    repo = ScenarioRepository()
    scenario = repo.get_scenario("cache_invalidation_lag")
    t0 = datetime.fromisoformat(scenario["incident_at"].replace("Z", "+00:00"))
    ledger = EvidenceLedger(incident_at=t0)
    service = DiagnosticService(scenario, ledger)

    service.query_telemetry()
    service.run_health_probes()
    service.fetch_operational_events()

    policy = PolicyEngine()
    evaluator = EvidenceEvaluator(policy)

    candidates = [
        RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
        RootCauseCode.DATABASE_CAPACITY_DEGRADATION,
        RootCauseCode.CACHE_NODE_FAILURE,
        RootCauseCode.TRAFFIC_SURGE,
    ]

    evaluated = evaluator.evaluate_hypotheses(candidates, ledger)
    by_code = {h.cause_code: h for h in evaluated}

    # 1. Consumer stalled:
    # Telemetry: cache_hit_ratio (2+2+2=6)
    # Events: invalidation_queue_backlog (3+2+3=8)
    # Net support = 6 + 8 = 14
    consumer_hyp = by_code[RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED]
    assert consumer_hyp.net_evidence_score >= 14.0
    assert consumer_hyp.strength_band == EvidenceStrengthBand.STRONG
    assert consumer_hyp.decision_weight > 70.0

    # 2. Database degradation:
    # Telemetry workload latency: +6
    # Opposing synthetic direct probe: -8 (verified=3, current=2, direct=3 = 8)
    # Net = max(0, 6 - 8) = 0.0
    db_hyp = by_code[RootCauseCode.DATABASE_CAPACITY_DEGRADATION]
    assert db_hyp.opposing_score >= 8.0
    assert db_hyp.net_evidence_score == 0.0
    assert db_hyp.decision_weight == 0.0
    assert db_hyp.strength_band == EvidenceStrengthBand.UNSUPPORTED


def test_four_dimensional_strategy_ranking() -> None:
    """Verify that consumer recovery wins overall, cache restart is fastest/cheapest but loses, and failover ranks last."""
    repo = ScenarioRepository()
    scenario = repo.get_scenario("cache_invalidation_lag")
    t0 = datetime.fromisoformat(scenario["incident_at"].replace("Z", "+00:00"))
    ledger = EvidenceLedger(incident_at=t0)
    service = DiagnosticService(scenario, ledger)

    service.query_telemetry()
    service.run_health_probes()
    service.fetch_operational_events()

    policy = PolicyEngine()
    evaluator = EvidenceEvaluator(policy)
    ranker = StrategyRanker(policy)

    candidates = [
        RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
        RootCauseCode.DATABASE_CAPACITY_DEGRADATION,
        RootCauseCode.CACHE_NODE_FAILURE,
        RootCauseCode.TRAFFIC_SURGE,
    ]

    evaluated = evaluator.evaluate_hypotheses(candidates, ledger)
    ranked = ranker.rank_strategies(evaluated)

    assert len(ranked) == 4
    # Winner must be RECOVER_CONSUMER_AND_DRAIN
    assert ranked[0].strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
    assert ranked[0].rank == 1
    assert ranked[0].final_score > 65.0

    # 2nd is THROTTLE_TRAFFIC
    assert ranked[1].strategy_id == "THROTTLE_TRAFFIC"
    assert ranked[1].rank == 2

    # 3rd is RESTART_CACHE (fastest at speed=100, but lower final score)
    assert ranked[2].strategy_id == "RESTART_CACHE"
    assert ranked[2].rank == 3
    assert ranked[2].speed == 100.0
    assert ranked[2].final_score < ranked[0].final_score

    # 4th is FAILOVER_DATABASE (lowest score)
    assert ranked[3].strategy_id == "FAILOVER_DATABASE"
    assert ranked[3].rank == 4
    assert ranked[3].final_score < 20.0
