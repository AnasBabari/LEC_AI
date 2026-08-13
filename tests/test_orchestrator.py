"""Integration tests for IncidentOrchestrator and end-to-end analysis lifecycle."""

from faultline.gemini import FakeGeminiProvider
from faultline.models import LifecycleState
from faultline.orchestrator import IncidentOrchestrator


def test_orchestrator_canonical_run() -> None:
    """Execute complete end-to-end incident investigation with FakeGeminiProvider."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)

    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # 1. Verification of lifecycle completion and validation
    assert result.state == LifecycleState.VALIDATED
    assert result.validation_passed is True
    assert result.run_id.startswith("RUN-")

    # 2. Verification of multi-source diagnostic collection
    assert len(result.evidence) == 9
    source_groups = {obs.source_group.value for obs in result.evidence}
    assert source_groups == {"telemetry", "health_probe", "operational_events"}

    # 3. Verification of conflicts and scope tension
    assert len(result.conflicts) >= 1
    db_conflict = next(c for c in result.conflicts if c.component == "database")
    assert db_conflict.conflict_type.value == "SCOPE_TENSION"

    # 4. Verification of hypotheses & scoring
    assert len(result.hypotheses) >= 3
    top_hyp = result.hypotheses[0]
    assert top_hyp.cause_code.value == "CACHE_INVALIDATION_CONSUMER_STALLED"
    assert top_hyp.net_evidence_score >= 14.0
    assert top_hyp.decision_weight > 70.0
    assert top_hyp.strength_band.value == "STRONG"

    # 5. Verification of 4D strategy ranking
    assert len(result.strategy_ranking) >= 4
    winner = result.strategy_ranking[0]
    assert winner.strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
    assert winner.rank == 1

    # Verify fastest alternative is present and ranked lower
    restart_cache = next(s for s in result.strategy_ranking if s.strategy_id == "RESTART_CACHE")
    assert restart_cache.speed == 100.0
    assert restart_cache.rank > 1
    assert restart_cache.final_score < winner.final_score

    # 6. Verification of trade-off defense and grounded explanation
    assert result.recommendation.winning_strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
    assert "RESTART_CACHE" in result.recommendation.trade_off_comparison.alternative_strategy_id
    assert len(result.recommendation.remaining_uncertainties) > 0

    # 7. Verification of safety preconditions
    assert result.execution.execution_status == "not_executed"
    assert result.execution.operator_approval_required is True

    # 8. Verification of timeline trace
    assert len(result.investigation_trace) >= 5


def test_orchestrator_index_regression_run() -> None:
    """Execute end-to-end incident investigation on secondary index_regression scenario."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)

    result = orchestrator.analyze_scenario("index_regression")

    assert result.state == LifecycleState.VALIDATED
    assert result.validation_passed is True
    assert len(result.conflicts) >= 1

    # Top hypothesis should be DATABASE_INDEX_REGRESSION
    assert result.hypotheses[0].cause_code.value == "DATABASE_INDEX_REGRESSION"
    assert result.hypotheses[0].net_evidence_score >= 14.0

    # Winning strategy should be REBUILD_DATABASE_INDEX
    assert result.strategy_ranking[0].strategy_id == "REBUILD_DATABASE_INDEX"
    assert result.strategy_ranking[0].rank == 1
    assert result.recommendation.winning_strategy_id == "REBUILD_DATABASE_INDEX"

