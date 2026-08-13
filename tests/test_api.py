"""API endpoint tests using FastAPI TestClient."""

from fastapi.testclient import TestClient

from faultline.app import app


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
        assert len(data["strategy_ranking"]) == 4

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
