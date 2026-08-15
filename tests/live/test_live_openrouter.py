"""Live smoke test verifying end-to-end investigation with OpenRouter API when OPENROUTER_API_KEY is configured."""

import os

import pytest
from dotenv import load_dotenv

from faultline.gemini import GeminiProvider
from faultline.models import LifecycleState
from faultline.orchestrator import IncidentOrchestrator

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
RUN_LIVE_TESTS = os.getenv("RUN_LIVE_TESTS", "").lower() in ("true", "1", "yes")


@pytest.mark.skipif(
    not OPENROUTER_API_KEY or not RUN_LIVE_TESTS,
    reason="Live OpenRouter test skipped (enable by setting RUN_LIVE_TESTS=true and OPENROUTER_API_KEY).",
)
def test_live_openrouter_investigation() -> None:
    """Run live investigation against OpenRouter API and verify report passes all deterministic validation invariants."""
    provider = GeminiProvider(
        api_key=None,
        openrouter_api_key=OPENROUTER_API_KEY,
        openrouter_model=os.getenv("OPENROUTER_FALLBACK_MODEL", "google/gemini-2.0-flash-001"),
    )
    orchestrator = IncidentOrchestrator(provider=provider)

    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # 1. State must reach validated
    assert result.state == LifecycleState.VALIDATED
    assert result.validation_passed is True

    # 2. Model execution metadata must reflect OpenRouter token usage
    assert result.model_execution.provider_used == "openrouter"
    assert result.model_execution.prompt_tokens is not None
    assert result.model_execution.prompt_tokens > 0

    # 3. Winning strategy must remain deterministic
    assert result.strategy_ranking[0].strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
    assert result.strategy_ranking[0].rank == 1
    assert result.recommendation.winning_strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
