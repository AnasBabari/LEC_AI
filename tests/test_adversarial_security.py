"""Adversarial security, boundary constraint, and error classification tests."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from faultline.app import app
from faultline.models import AnalyzeRequest
from faultline.reasoning import EvidenceEvaluator, PolicyEngine


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_cors_headers_restricted_origins(client: TestClient) -> None:
    """Verify CORS headers only reflect explicitly allowed origins and disallow wildcard with credentials."""
    # Allowed origin
    res = client.options(
        "/api/analyze",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert res.headers.get("access-control-allow-credentials") == "true"

    # Disallowed untrusted origin
    res_bad = client.options(
        "/api/analyze",
        headers={
            "Origin": "https://malicious-attacker.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res_bad.headers.get("access-control-allow-origin") != "https://malicious-attacker.com"


def test_analyze_request_pattern_and_length_validation() -> None:
    """Verify AnalyzeRequest blocks path traversal characters and overlong input."""
    # Valid
    req = AnalyzeRequest(scenario_id="cache_invalidation_lag")
    assert req.scenario_id == "cache_invalidation_lag"

    # Path traversal attack pattern
    with pytest.raises(Exception):
        AnalyzeRequest(scenario_id="../../../etc/passwd")

    # Invalid characters (spaces, semicolons, script tags)
    with pytest.raises(Exception):
        AnalyzeRequest(scenario_id="scenario; DROP TABLE users;")

    with pytest.raises(Exception):
        AnalyzeRequest(scenario_id="<script>alert(1)</script>")

    # Overly long scenario ID (> 128 chars)
    with pytest.raises(Exception):
        AnalyzeRequest(scenario_id="a" * 129)


def test_timezone_mixed_freshness_computation_defense() -> None:
    """Verify EvidenceEvaluator handles offset-naive and offset-aware datetime arithmetic safely."""
    policy = PolicyEngine()
    evaluator = EvidenceEvaluator(policy)

    # Offset-naive observed_at vs UTC incident_at
    naive_observed = datetime(2026, 8, 15, 12, 0, 0)
    utc_incident = datetime(2026, 8, 15, 12, 2, 0, tzinfo=timezone.utc)

    # Must not raise TypeError: can't subtract offset-naive and offset-aware datetimes
    score = evaluator._compute_freshness_score(naive_observed, utc_incident)
    assert score in (
        policy.freshness_weights["current"],
        policy.freshness_weights["recent"],
        policy.freshness_weights["stale"],
    )

    # UTC observed_at vs offset-naive incident_at
    utc_observed = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
    naive_incident = datetime(2026, 8, 15, 12, 2, 0)

    score2 = evaluator._compute_freshness_score(utc_observed, naive_incident)
    assert score2 == score


def test_policy_engine_immutability_encapsulation() -> None:
    """Verify mutating internal policy dictionaries does not affect other PolicyEngine instances."""
    engine1 = PolicyEngine()
    engine2 = PolicyEngine()

    # Mutate dict in engine1
    engine1.scoring_weights["test_mutation"] = 999.0

    # engine2 must not have mutated
    assert "test_mutation" not in engine2.scoring_weights
