"""Tests for GeminiProvider and FakeGeminiProvider."""

from datetime import datetime, timezone

from faultline.diagnostics import DiagnosticService, EvidenceLedger, ScenarioRepository
from faultline.gemini import FakeGeminiProvider, GeminiProvider
from faultline.models import (
    FaultReport,
    RootCauseCode,
)
from faultline.reasoning import ConflictDetector, EvidenceEvaluator, PolicyEngine, StrategyRanker


def test_fake_gemini_provider_lifecycle() -> None:
    """Verify FakeGeminiProvider diagnostic selection, hypothesis synthesis, and decision explanation."""
    repo = ScenarioRepository()
    scenario = repo.get_scenario("cache_invalidation_lag")
    t0 = datetime.fromisoformat(scenario["incident_at"].replace("Z", "+00:00"))
    ledger = EvidenceLedger(incident_at=t0)
    service = DiagnosticService(scenario, ledger)

    provider = FakeGeminiProvider()
    incident = FaultReport(
        source=scenario["initial_fault_report"]["source"],
        severity=scenario["initial_fault_report"]["severity"],
        headline=scenario["initial_fault_report"]["headline"],
        reported_at=t0,
        details=scenario["initial_fault_report"]["details"],
    )

    # 1. Round 1: Choose diagnostics
    batch1 = provider.choose_diagnostics(
        incident=incident,
        evidence_ledger=ledger.get_observations(),
        round_index=1,
        available_tools=["query_telemetry", "run_health_probes", "fetch_operational_events"],
        remaining_attempts=5,
    )
    assert len(batch1.tool_calls) == 2
    assert not batch1.investigation_complete

    # Execute tools
    service.query_telemetry()
    service.run_health_probes()

    # 2. Round 2: Choose operational events
    batch2 = provider.choose_diagnostics(
        incident=incident,
        evidence_ledger=ledger.get_observations(),
        round_index=2,
        available_tools=["query_telemetry", "run_health_probes", "fetch_operational_events"],
        remaining_attempts=3,
    )
    assert len(batch2.tool_calls) == 1
    assert batch2.tool_calls[0].tool_name == "fetch_operational_events"

    service.fetch_operational_events()

    # 3. Round 3: All collected -> investigation_complete
    batch3 = provider.choose_diagnostics(
        incident=incident,
        evidence_ledger=ledger.get_observations(),
        round_index=3,
        available_tools=["query_telemetry", "run_health_probes", "fetch_operational_events"],
        remaining_attempts=2,
    )
    assert batch3.investigation_complete

    # 4. Hypothesis synthesis
    allowed_causes = list(RootCauseCode)
    hyp_set = provider.synthesise_hypotheses(incident, ledger.get_observations(), allowed_causes)
    assert len(hyp_set.hypotheses) >= 3
    # Check that cited IDs exist in the ledger
    ledger_ids = {obs.id for obs in ledger.get_observations()}
    for h in hyp_set.hypotheses:
        for ev_id in h.supporting_evidence_ids:
            assert ev_id in ledger_ids
        for ev_id in h.opposing_evidence_ids:
            assert ev_id in ledger_ids

    # 5. Deterministic reasoning
    policy = PolicyEngine()
    evaluator = EvidenceEvaluator(policy)
    ranker = StrategyRanker(policy)
    conflicts = ConflictDetector.detect_conflicts(ledger)
    evaluated = evaluator.evaluate_hypotheses(
        candidate_codes=[h.cause_code for h in hyp_set.hypotheses],
        ledger=ledger,
        draft_hypotheses=hyp_set.hypotheses,
    )
    ranked = ranker.rank_strategies(evaluated)

    # 6. Decision explanation
    explanation = provider.explain_decision(
        incident=incident,
        evidence_ledger=ledger.get_observations(),
        conflicts=conflicts,
        hypotheses=evaluated,
        strategy_ranking=ranked,
        winning_strategy=ranked[0],
        top_alternative=ranked[2], # RESTART_CACHE (fastest)
    )

    assert explanation.winning_strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
    assert "RESTART_CACHE" in explanation.trade_off_comparison.alternative_strategy_id
    assert "stampede" in explanation.trade_off_comparison.rejection_rationale.lower()
    assert len(explanation.remaining_uncertainties) > 0


def test_gemini_provider_offline_fallback() -> None:
    """Verify GeminiProvider gracefully operates in stub mode when no API key is set."""
    provider = GeminiProvider(api_key=None, preferred_model="gemini-3.6-flash")
    meta = provider.get_execution_metadata()
    assert meta.model_used == "gemini-3.6-flash"
    assert not meta.fallback_occurred
