"""Live smoke test verifying end-to-end investigation with real Gemini API when GEMINI_API_KEY is configured."""

import os

import pytest
from dotenv import load_dotenv

from faultline.gemini import GeminiProvider
from faultline.models import LifecycleState
from faultline.orchestrator import IncidentOrchestrator

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RUN_LIVE_TESTS = os.getenv("RUN_LIVE_TESTS", "").lower() in ("true", "1", "yes")


@pytest.mark.skipif(
    not GEMINI_API_KEY or not RUN_LIVE_TESTS,
    reason="Live Gemini test skipped (enable by setting RUN_LIVE_TESTS=true and GEMINI_API_KEY).",
)
def test_live_gemini_investigation() -> None:
    """Run live investigation against Google Gemini API and verify report passes all deterministic validation invariants."""
    provider = GeminiProvider(api_key=GEMINI_API_KEY)
    orchestrator = IncidentOrchestrator(provider=provider)

    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # 1. State must reach validated
    assert result.state == LifecycleState.VALIDATED
    assert result.validation_passed is True

    # 2. Model execution metadata must reflect real token consumption
    assert result.model_execution.model_used in ("gemini-3.7-flash", "gemini-3.6-flash")
    assert result.model_execution.prompt_tokens is not None
    assert result.model_execution.prompt_tokens > 0
    assert result.model_execution.completion_tokens is not None
    assert result.model_execution.completion_tokens > 0

    # 3. Winning strategy must remain deterministic
    assert result.strategy_ranking[0].strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
    assert result.strategy_ranking[0].rank == 1
    assert result.recommendation.winning_strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
