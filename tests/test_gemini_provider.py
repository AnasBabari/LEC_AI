"""Tests for GeminiProvider, FakeGeminiProvider, and InvestigationSession isolation."""

from datetime import datetime

from faultline.diagnostics import DiagnosticService, EvidenceLedger, ScenarioRepository
from faultline.gemini import FakeGeminiProvider, GeminiProvider, InvestigationSession
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
        top_alternative=ranked[2],  # RESTART_CACHE (fastest)
    )

    assert explanation.winning_strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
    assert "RESTART_CACHE" in explanation.trade_off_comparison.alternative_strategy_id
    assert "stampede" in explanation.trade_off_comparison.rejection_rationale.lower()
    assert len(explanation.remaining_uncertainties) > 0


def test_fake_gemini_provider_offline_metadata() -> None:
    """Verify FakeGeminiProvider truthfully reports offline fake mode and null tokens."""
    provider = FakeGeminiProvider()
    meta = provider.get_execution_metadata()
    assert meta.model_used == "offline-deterministic-fake"
    assert meta.thinking_level == "none"
    assert meta.prompt_tokens is None
    assert meta.completion_tokens is None
    assert meta.fallback_occurred is False


def test_gemini_provider_offline_fallback(monkeypatch) -> None:
    """Verify GeminiProvider gracefully operates in stub mode when no API key is available."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider(api_key="")
    meta = provider.get_execution_metadata()
    assert meta.configured_primary_model == "gemini-3.7-flash"
    assert meta.model_used == "offline-deterministic-fake"
    assert not meta.fallback_occurred

    provider_36 = GeminiProvider(api_key="", preferred_model="gemini-3.6-flash")
    meta_36 = provider_36.get_execution_metadata()
    assert meta_36.configured_primary_model == "gemini-3.6-flash"
    assert meta_36.model_used == "offline-deterministic-fake"


def test_investigation_session_isolation() -> None:
    """Verify InvestigationSession isolates execution metrics across sequential and concurrent runs."""
    session1 = InvestigationSession(
        configured_primary="gemini-3.7-flash",
        configured_fallback="gemini-3.6-flash",
        default_model="gemini-3.7-flash",
    )
    session2 = InvestigationSession(
        configured_primary="gemini-3.7-flash",
        configured_fallback="gemini-3.6-flash",
        default_model="gemini-3.7-flash",
    )

    # Session 1 records a fallback call with token usage
    session1.record_call(
        task="choose_diagnostics",
        model="gemini-3.6-flash",
        fallback_used=True,
        fallback_reason="service_unavailable (RuntimeError)",
        prompt_tokens=450,
        completion_tokens=120,
    )

    # Session 2 records normal primary call
    session2.record_call(
        task="synthesise_hypotheses",
        model="gemini-3.7-flash",
        fallback_used=False,
        prompt_tokens=300,
        completion_tokens=80,
    )

    meta1 = session1.get_execution_metadata()
    meta2 = session2.get_execution_metadata()

    # Session 1 state
    assert meta1.model_used == "gemini-3.6-flash"
    assert "gemini-3.6-flash" in meta1.models_used
    assert len(meta1.call_trace) == 1
    assert meta1.call_trace[0].task == "choose_diagnostics"
    assert meta1.fallback_occurred is True
    assert meta1.fallback_reason == "service_unavailable (RuntimeError)"
    assert meta1.prompt_tokens == 450
    assert meta1.completion_tokens == 120

    # Session 2 state must NOT inherit Session 1 state
    assert meta2.model_used == "gemini-3.7-flash"
    assert meta2.models_used == ["gemini-3.7-flash"]
    assert len(meta2.call_trace) == 1
    assert meta2.call_trace[0].task == "synthesise_hypotheses"
    assert meta2.fallback_occurred is False
    assert meta2.fallback_reason is None
    assert meta2.prompt_tokens == 300
    assert meta2.completion_tokens == 80
