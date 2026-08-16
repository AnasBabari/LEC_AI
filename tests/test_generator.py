"""Tests for the Procedural Incident Synthesis Engine and Dynamic Incident Resolution."""

from datetime import datetime

import pytest

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


@pytest.mark.parametrize(
    ("archetype", "expected_strategy"),
    [
        ("CACHE_INVALIDATION_CONSUMER_STALLED", "RECOVER_CONSUMER_AND_DRAIN"),
        ("DATABASE_INDEX_REGRESSION", "REBUILD_DATABASE_INDEX"),
        ("FLASH_SALE_SURGE", "THROTTLE_TRAFFIC"),
        ("CACHE_CLUSTER_OUTAGE", "RESTART_CACHE"),
        ("REPLICA_REPLICATION_LAG", "THROTTLE_TRAFFIC"),
        ("DATABASE_CAPACITY_DEGRADATION", "THROTTLE_TRAFFIC"),
    ],
)
def test_generated_archetype_resolves_to_expected_strategy(
    archetype: str,
    expected_strategy: str,
) -> None:
    """Verify that all 6 procedural generator archetypes consistently resolve to their expected winning strategy across seeds."""
    for seed in (42, 101, 777):
        engine = IncidentSynthesisEngine(seed=seed)
        incident_data = engine.generate_incident(archetype=archetype)

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
        assert result.strategy_ranking[0].strategy_id == expected_strategy

        validator = ReportValidator(policy)
        assert validator.validate(result) is True


@pytest.mark.parametrize(
    "archetype",
    [
        "CACHE_INVALIDATION_CONSUMER_STALLED",
        "DATABASE_INDEX_REGRESSION",
        "FLASH_SALE_SURGE",
        "CACHE_CLUSTER_OUTAGE",
        "REPLICA_REPLICATION_LAG",
        "DATABASE_CAPACITY_DEGRADATION",
    ],
)
def test_generated_narrative_numerical_grounding(archetype: str) -> None:
    """Verify that offline narrative explanations and causal chains extract exact numerical values from generated evidence."""
    for seed in (42, 101, 777):
        engine = IncidentSynthesisEngine(seed=seed)
        incident_data = engine.generate_incident(archetype=archetype)

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
        contradiction_text = result.recommendation.grounded_contradiction_analysis
        top_chain = " ".join(result.hypotheses[0].causal_chain)

        # Check that specific archetype measurements in evidence appear in the contradiction text or causal chain
        if archetype == "DATABASE_INDEX_REGRESSION":
            # Table scan rate
            table_scan_obs = next(
                (o for o in result.evidence if o.signal == "database_table_scan_rate"),
                None,
            )
            assert table_scan_obs is not None
            scan_val_str = f"{table_scan_obs.value:.1f}{table_scan_obs.unit}" if not table_scan_obs.value.is_integer() else f"{int(table_scan_obs.value):,}{table_scan_obs.unit}"
            assert scan_val_str in contradiction_text or scan_val_str in top_chain

        elif archetype == "CACHE_INVALIDATION_CONSUMER_STALLED":
            # Queue backlog count
            mq_obs = next(
                (o for o in result.evidence if o.component.value == "message_queue" and o.dimension.value == "backlog"),
                None,
            )
            assert mq_obs is not None
            mq_val_str = f"{int(mq_obs.value):,}{mq_obs.unit}"
            assert mq_val_str in contradiction_text or mq_val_str in top_chain

        elif archetype == "REPLICA_REPLICATION_LAG":
            # Replica lag seconds
            lag_obs = next(
                (o for o in result.evidence if o.signal == "replica_lag_seconds"),
                None,
            )
            assert lag_obs is not None
            lag_val_str = f"{int(lag_obs.value):,}{lag_obs.unit}" if lag_obs.value.is_integer() else f"{lag_obs.value:.1f}{lag_obs.unit}"
            assert lag_val_str in contradiction_text or lag_val_str in top_chain

        elif archetype == "FLASH_SALE_SURGE":
            # API Gateway throughput or latency
            tput_obs = next(
                (o for o in result.evidence if o.component.value == "api_gateway" and o.dimension.value == "throughput"),
                None,
            )
            assert tput_obs is not None
            tput_val_str = f"{tput_obs.value:.1f}{tput_obs.unit}" if not tput_obs.value.is_integer() else f"{int(tput_obs.value):,}{tput_obs.unit}"
            assert tput_val_str in contradiction_text or tput_val_str in top_chain

        elif archetype == "CACHE_CLUSTER_OUTAGE":
            # Cache availability
            cache_obs = next(
                (o for o in result.evidence if o.component.value == "cache" and o.dimension.value == "availability"),
                None,
            )
            assert cache_obs is not None
            cache_val_str = f"{cache_obs.value:.1f}{cache_obs.unit}" if not cache_obs.value.is_integer() else f"{int(cache_obs.value):,}{cache_obs.unit}"
            assert cache_val_str in contradiction_text or cache_val_str in top_chain

        elif archetype == "DATABASE_CAPACITY_DEGRADATION":
            # Database connection pool load
            pool_obs = next(
                (o for o in result.evidence if o.component.value == "database" and o.signal == "connection_pool_load_pct"),
                None,
            )
            assert pool_obs is not None
            pool_val_str = f"{pool_obs.value:.1f}{pool_obs.unit}" if not pool_obs.value.is_integer() else f"{int(pool_obs.value):,}{pool_obs.unit}"
            assert pool_val_str in contradiction_text or pool_val_str in top_chain





