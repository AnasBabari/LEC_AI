"""Tests for the Procedural Incident Synthesis Engine and Dynamic Incident Resolution."""

from datetime import datetime

from faultline.diagnostics import ScenarioRepository
from faultline.gemini import FakeGeminiProvider
from faultline.generator import IncidentSynthesisEngine
from faultline.models import AnalysisResult, ComponentEnum
from faultline.orchestrator import IncidentOrchestrator
from faultline.reasoning import PolicyEngine
from faultline.validation import ReportValidator


def test_generator_all_archetypes() -> None:
    """Verify that all archetypes can be generated with complete diagnostic datasets."""
    engine = IncidentSynthesisEngine(seed=42)
    for archetype in IncidentSynthesisEngine.ARCHETYPES:
        incident = engine.generate_incident(archetype=archetype)
        assert incident["id"].startswith("inc_")
        assert len(incident["title"]) > 5
        assert len(incident["description"]) > 10
        assert len(incident["affected_components"]) >= 2
        assert "incident_at" in incident
        dt = datetime.fromisoformat(incident["incident_at"])
        assert dt is not None

        diagnostics = incident["diagnostics"]
        assert len(diagnostics["telemetry"]) >= 4
        assert len(diagnostics["health_probe"]) >= 2
        assert len(diagnostics["operational_events"]) >= 2


def test_generator_deterministic_seed_reproducibility() -> None:
    """Verify that using the same seed produces identical incidents."""
    engine1 = IncidentSynthesisEngine(seed=12345)
    incident1 = engine1.generate_incident(
        archetype="CACHE_INVALIDATION_CONSUMER_STALLED",
        incident_time=datetime(2026, 8, 16, 12, 0, 0),
        incident_id="inc_test_12345",
    )

    engine2 = IncidentSynthesisEngine(seed=12345)
    incident2 = engine2.generate_incident(
        archetype="CACHE_INVALIDATION_CONSUMER_STALLED",
        incident_time=datetime(2026, 8, 16, 12, 0, 0),
        incident_id="inc_test_12345",
    )

    assert incident1 == incident2


def test_generator_stress_test_100_random_incidents() -> None:
    """Stress test: generate 100 random incidents and verify complete schema integrity."""
    engine = IncidentSynthesisEngine()
    for _ in range(100):
        incident = engine.generate_incident()
        assert incident["id"].startswith("inc_")
        assert all(isinstance(c, str) for c in incident["affected_components"])
        for item in incident["diagnostics"]["telemetry"]:
            assert item["component"] in [c.value for c in ComponentEnum]
            assert isinstance(item["value"], (int, float))
            assert item["value"] >= 0.0


def test_dynamic_incident_end_to_end_orchestrator_resolution() -> None:
    """Test full automated investigation and validation of a synthesized incident."""
    engine = IncidentSynthesisEngine(seed=999)
    incident_data = engine.generate_incident(archetype="CACHE_INVALIDATION_CONSUMER_STALLED")

    repo = ScenarioRepository()
    incident_id = repo.register_dynamic_scenario(incident_data)

    policy = PolicyEngine()
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(
        provider=provider,
        policy=policy,
        scenario_repo=repo,
    )

    result = orchestrator.analyze_scenario(incident_id)
    assert isinstance(result, AnalysisResult)
    assert result.scenario_id == incident_id
    assert len(result.hypotheses) >= 2
    assert len(result.strategy_ranking) == 5
    assert result.strategy_ranking[0].strategy_id == "RECOVER_CONSUMER_AND_DRAIN"

    # Verify report validation gate passes
    validator = ReportValidator(policy)
    assert validator.validate(result) is True



