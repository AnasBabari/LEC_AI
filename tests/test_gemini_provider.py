"""Tests for GeminiProvider, FakeGeminiProvider, error classification, and InvestigationSession isolation."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from google.genai import errors

from faultline.diagnostics import DiagnosticService, EvidenceLedger, ScenarioRepository
from faultline.gemini import (
    FakeGeminiProvider,
    GeminiProvider,
    classify_model_error,
)
from faultline.models import (
    DiagnosticToolName,
    FaultReport,
    InvalidModelOutputError,
    ModelAuthenticationError,
    ModelRequestError,
    ModelUnavailableError,
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
    assert batch2.tool_calls[0].tool_name == DiagnosticToolName.FETCH_OPERATIONAL_EVENTS

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

    assert ranked[0].name in explanation.executive_summary
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


def test_gemini_provider_offline_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_error_classification_status_codes() -> None:
    """Verify structured status code error classification."""
    # 400 Bad Request
    err400 = errors.APIError(400, {"message": "Invalid argument"})
    eligible, cat = classify_model_error(err400)
    assert eligible is False
    assert "bad_request_400" in cat

    # 401 Unauthorized
    err401 = errors.APIError(401, {"message": "API key not valid"})
    eligible, cat = classify_model_error(err401)
    assert eligible is False
    assert "authentication_failed_401" in cat

    # 404 Model Not Found -> eligible for fallback
    err404 = errors.APIError(404, {"message": "Model not found"})
    eligible, cat = classify_model_error(err404)
    assert eligible is True
    assert "model_not_found_404" in cat

    # 429 Rate Limit -> eligible for fallback
    err429 = errors.APIError(429, {"message": "Resource exhausted"})
    eligible, cat = classify_model_error(err429)
    assert eligible is True
    assert "rate_limit_exceeded_429" in cat

    # 503 Unavailable -> eligible for fallback
    err503 = errors.APIError(503, {"message": "Service Unavailable"})
    eligible, cat = classify_model_error(err503)
    assert eligible is True
    assert "service_unavailable_503" in cat

    # Timeout
    timeout_err = TimeoutError("Request timed out")
    eligible, cat = classify_model_error(timeout_err)
    assert eligible is True
    assert "request_timeout" in cat


def test_mock_gemini_primary_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify successful primary model call with token tracking."""
    provider = GeminiProvider(api_key="dummy-key")
    mock_client = MagicMock()
    provider._client = mock_client

    mock_resp = MagicMock()
    mock_resp.text = '{"tool_calls": [{"tool_name": "query_telemetry", "reasoning": "Check metrics"}], "investigation_complete": false}'
    mock_resp.usage_metadata.prompt_token_count = 100
    mock_resp.usage_metadata.candidates_token_count = 50
    mock_client.models.generate_content.return_value = mock_resp

    session = provider.create_session()
    batch = provider.choose_diagnostics(
        incident=MagicMock(headline="Test", severity="high", details="Details"),
        evidence_ledger=[],
        round_index=1,
        available_tools=["query_telemetry"],
        remaining_attempts=3,
        session=session,
    )
    assert len(batch.tool_calls) == 1
    assert batch.tool_calls[0].tool_name == DiagnosticToolName.QUERY_TELEMETRY
    assert session.prompt_tokens == 100
    assert session.completion_tokens == 50
    assert not session.fallback_occurred


def test_mock_gemini_400_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify 400 Bad Request raises ModelRequestError without triggering fallback."""
    provider = GeminiProvider(api_key="dummy-key", preferred_model="gemini-3.7-flash", fallback_model="gemini-3.6-flash")
    mock_client = MagicMock()
    provider._client = mock_client

    mock_client.models.generate_content.side_effect = errors.APIError(400, {"message": "Bad argument"})

    session = provider.create_session()
    with pytest.raises(ModelRequestError) as excinfo:
        provider.choose_diagnostics(
            incident=MagicMock(headline="Test", severity="high", details="Details"),
            evidence_ledger=[],
            round_index=1,
            available_tools=["query_telemetry"],
            remaining_attempts=3,
            session=session,
        )
    assert "Bad request to model 'gemini-3.7-flash'" in str(excinfo.value)
    assert mock_client.models.generate_content.call_count == 1


def test_mock_gemini_401_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify 401 Unauthorized raises ModelAuthenticationError without fallback."""
    provider = GeminiProvider(api_key="dummy-key", preferred_model="gemini-3.7-flash", fallback_model="gemini-3.6-flash")
    mock_client = MagicMock()
    provider._client = mock_client

    mock_client.models.generate_content.side_effect = errors.APIError(401, {"message": "Key invalid"})

    session = provider.create_session()
    with pytest.raises(ModelAuthenticationError):
        provider.choose_diagnostics(
            incident=MagicMock(headline="Test", severity="high", details="Details"),
            evidence_ledger=[],
            round_index=1,
            available_tools=["query_telemetry"],
            remaining_attempts=3,
            session=session,
        )
    assert mock_client.models.generate_content.call_count == 1


def test_mock_gemini_429_triggers_sticky_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify 429 triggers fallback to 3.6, and subsequent calls stay on 3.6 (sticky)."""
    provider = GeminiProvider(api_key="dummy-key", preferred_model="gemini-3.7-flash", fallback_model="gemini-3.6-flash")
    mock_client = MagicMock()
    provider._client = mock_client

    # First call: 3.7 raises 429, 3.6 succeeds
    mock_resp_36 = MagicMock()
    mock_resp_36.text = '{"tool_calls": [], "investigation_complete": true}'
    mock_resp_36.usage_metadata.prompt_token_count = 80
    mock_resp_36.usage_metadata.candidates_token_count = 20

    def mock_generate(model: str, contents: str, config: object) -> MagicMock:
        if model == "gemini-3.7-flash":
            raise errors.APIError(429, {"message": "Quota exceeded"})
        elif model == "gemini-3.6-flash":
            return mock_resp_36
        raise ValueError(f"Unexpected model: {model}")

    mock_client.models.generate_content.side_effect = mock_generate

    session = provider.create_session()
    batch1 = provider.choose_diagnostics(
        incident=MagicMock(headline="Test", severity="high", details="Details"),
        evidence_ledger=[],
        round_index=1,
        available_tools=["query_telemetry"],
        remaining_attempts=3,
        session=session,
    )
    assert batch1.investigation_complete is True
    assert session.active_model == "gemini-3.6-flash"
    assert session.fallback_occurred is True

    # Second call in same session: must immediately target 3.6 without retrying 3.7
    mock_client.models.generate_content.reset_mock()
    mock_client.models.generate_content.side_effect = mock_generate

    batch2 = provider.choose_diagnostics(
        incident=MagicMock(headline="Test", severity="high", details="Details"),
        evidence_ledger=[],
        round_index=2,
        available_tools=["query_telemetry"],
        remaining_attempts=2,
        session=session,
    )
    assert batch2.investigation_complete is True
    # Verify generate_content was called ONLY once, targeting gemini-3.6-flash
    assert mock_client.models.generate_content.call_count == 1
    call_kwargs = mock_client.models.generate_content.call_args[1]
    assert call_kwargs["model"] == "gemini-3.6-flash"


def test_mock_gemini_schema_repair_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify 1 same-model schema repair occurs when initial JSON fails schema validation."""
    provider = GeminiProvider(api_key="dummy-key", preferred_model="gemini-3.7-flash", fallback_model="gemini-3.6-flash")
    mock_client = MagicMock()
    provider._client = mock_client

    bad_resp = MagicMock()
    bad_resp.text = '{"tool_calls": "invalid_type_not_a_list"}'
    bad_resp.usage_metadata.prompt_token_count = 50
    bad_resp.usage_metadata.candidates_token_count = 10

    good_resp = MagicMock()
    good_resp.text = '{"tool_calls": [], "investigation_complete": true}'
    good_resp.usage_metadata.prompt_token_count = 70
    good_resp.usage_metadata.candidates_token_count = 15

    mock_client.models.generate_content.side_effect = [bad_resp, good_resp]

    session = provider.create_session()
    batch = provider.choose_diagnostics(
        incident=MagicMock(headline="Test", severity="high", details="Details"),
        evidence_ledger=[],
        round_index=1,
        available_tools=["query_telemetry"],
        remaining_attempts=3,
        session=session,
    )
    assert batch.investigation_complete is True
    assert mock_client.models.generate_content.call_count == 2
    assert len(session.call_trace) == 2
    assert session.call_trace[1].task == "choose_diagnostics_repair"


def test_mock_gemini_schema_repair_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that when schema repair also produces invalid JSON, InvalidModelOutputError is raised."""
    provider = GeminiProvider(api_key="dummy-key", preferred_model="gemini-3.7-flash", fallback_model="gemini-3.6-flash")
    mock_client = MagicMock()
    provider._client = mock_client

    bad_resp = MagicMock()
    bad_resp.text = '{"tool_calls": "invalid_type_not_a_list"}'

    mock_client.models.generate_content.side_effect = [bad_resp, bad_resp]

    session = provider.create_session()
    with pytest.raises(InvalidModelOutputError):
        provider.choose_diagnostics(
            incident=MagicMock(headline="Test", severity="high", details="Details"),
            evidence_ledger=[],
            round_index=1,
            available_tools=["query_telemetry"],
            remaining_attempts=3,
            session=session,
        )


def test_mock_gemini_both_models_fail_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that if both primary and fallback fail with 503, ModelUnavailableError is raised."""
    provider = GeminiProvider(api_key="dummy-key", preferred_model="gemini-3.7-flash", fallback_model="gemini-3.6-flash")
    mock_client = MagicMock()
    provider._client = mock_client

    mock_client.models.generate_content.side_effect = errors.APIError(503, {"message": "Outage"})

    session = provider.create_session()
    with pytest.raises(ModelUnavailableError) as excinfo:
        provider.choose_diagnostics(
            incident=MagicMock(headline="Test", severity="high", details="Details"),
            evidence_ledger=[],
            round_index=1,
            available_tools=["query_telemetry"],
            remaining_attempts=3,
            session=session,
        )
    assert "Both primary and fallback models failed" in str(excinfo.value)
