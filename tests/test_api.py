from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from faultline.app import app
from faultline.diagnostics import ScenarioRepository
from faultline.gemini import FakeGeminiProvider
from faultline.orchestrator import IncidentOrchestrator
from faultline.reasoning import PolicyEngine


@pytest.fixture(autouse=True)
def configure_test_provider() -> None:
    """Ensure API tests run with deterministic provider."""
    provider = FakeGeminiProvider()
    policy = PolicyEngine()
    repo = ScenarioRepository()
    app.state.provider = provider
    app.state.policy = policy
    app.state.scenario_repo = repo
    app.state.orchestrator = IncidentOrchestrator(
        provider=provider,
        policy=policy,
        scenario_repo=repo,
    )


def test_health_endpoint() -> None:
    """Test GET /health returns 200 and system metadata."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "faultline"
        assert "gemini_configured" in data


def test_list_scenarios_endpoint() -> None:
    """Test GET /api/scenarios lists available scenarios."""
    with TestClient(app) as client:
        response = client.get("/api/scenarios")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        scenario_ids = [s["id"] for s in data]
        assert "cache_invalidation_lag" in scenario_ids


def test_analyze_endpoint_canonical_success() -> None:
    """Test POST /api/analyze executes full analysis and returns validated result."""
    with TestClient(app) as client:
        payload = {"scenario_id": "cache_invalidation_lag"}
        response = client.post("/api/analyze", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["scenario_id"] == "cache_invalidation_lag"
        assert data["state"] == "VALIDATED"
        assert data["validation_passed"] is True
        assert len(data["evidence"]) == 9
        assert len(data["conflicts"]) >= 1
        assert len(data["hypotheses"]) >= 3
        assert len(data["strategy_ranking"]) >= 4

        # Verify strategy ranking winner
        assert data["strategy_ranking"][0]["strategy_id"] == "RECOVER_CONSUMER_AND_DRAIN"
        assert data["strategy_ranking"][0]["rank"] == 1
        assert data["recommendation"]["winning_strategy_id"] == "RECOVER_CONSUMER_AND_DRAIN"

        # Verify safety boundary
        assert data["execution"]["execution_status"] == "not_executed"
        assert data["execution"]["operator_approval_required"] is True


def test_analyze_endpoint_unknown_scenario() -> None:
    """Test POST /api/analyze returns 404 for unknown scenario ID."""
    with TestClient(app) as client:
        payload = {"scenario_id": "non_existent_scenario"}
        response = client.post("/api/analyze", json=payload)
        assert response.status_code == 404


def test_unknown_api_route_returns_404_json() -> None:
    """Test unknown /api/* routes return 404 JSON, not HTML SPA fallback."""
    with TestClient(app) as client:
        response = client.get("/api/does-not-exist")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")


def test_path_traversal_scenario_returns_error() -> None:
    """Test path traversal scenario payload is rejected with 422 validation error or 404."""
    with TestClient(app) as client:
        payload = {"scenario_id": "../policy"}
        response = client.post("/api/analyze", json=payload)
        assert response.status_code in (404, 422)

        # Valid formatted ID that doesn't exist returns 404
        payload_missing = {"scenario_id": "nonexistent_scenario_fixture"}
        response_missing = client.post("/api/analyze", json=payload_missing)
        assert response_missing.status_code == 404


def test_frontend_path_traversal_is_blocked() -> None:
    """Test encoded or relative path traversal sequences cannot escape frontend directory."""
    with TestClient(app) as client:
        # Attempt to read pyproject.toml via encoded traversal
        response = client.get("/%2e%2e/%2e%2e/pyproject.toml")
        # Must return 404 or index.html, never raw pyproject.toml file content
        assert "[project]" not in response.text

        response_env = client.get("/%2e%2e/%2e%2e/.env")
        assert "GEMINI_API_KEY" not in response_env.text


def test_internal_server_error_sanitization() -> None:
    """Test that unhandled errors log internally and return generic sanitized message with ID."""
    with TestClient(app) as client:
        mock_orch = MagicMock()
        mock_orch.analyze_scenario.side_effect = RuntimeError("Sensitive internal database path: /var/secrets/key.db")
        app.state.orchestrator = mock_orch

        response = client.post("/api/analyze", json={"scenario_id": "cache_invalidation_lag"})
        assert response.status_code == 500
        detail = response.json().get("detail", "")
        assert "/var/secrets" not in detail
        assert "Internal incident analysis failure" in detail
        assert "Incident reference ID: ERR-" in detail


def test_domain_error_http_mappings() -> None:
    """Verify domain exceptions map to expected HTTP status codes (400, 503, 504)."""
    from faultline.models import AnalysisTimeoutError, ModelRequestError, ModelUnavailableError

    with TestClient(app) as client:
        # 1. ModelRequestError -> 400
        mock_orch = MagicMock()
        mock_orch.analyze_scenario.side_effect = ModelRequestError("Bad argument sent to model")
        app.state.orchestrator = mock_orch
        resp400 = client.post("/api/analyze", json={"scenario_id": "cache_invalidation_lag"})
        assert resp400.status_code == 400
        assert "Upstream model request invalid" in resp400.json()["detail"]

        # 2. ModelUnavailableError -> 503
        mock_orch.analyze_scenario.side_effect = ModelUnavailableError("Both models failed")
        resp503 = client.post("/api/analyze", json={"scenario_id": "cache_invalidation_lag"})
        assert resp503.status_code == 503
        assert "Model provider is currently unavailable" in resp503.json()["detail"]

        # 3. AnalysisTimeoutError -> 504
        mock_orch.analyze_scenario.side_effect = AnalysisTimeoutError("Request deadline exceeded")
        resp504 = client.post("/api/analyze", json={"scenario_id": "cache_invalidation_lag"})
        assert resp504.status_code == 504
        assert "Analysis timed out" in resp504.json()["detail"]
