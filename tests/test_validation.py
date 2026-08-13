"""Unit tests for ReportValidator assertions and safety invariants."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from faultline.diagnostics import ScenarioRepository
from faultline.gemini import FakeGeminiProvider
from faultline.models import (
    FaultReport,
    HypothesisDraft,
    HypothesisDraftSet,
    RootCauseCode,
)
from faultline.orchestrator import IncidentOrchestrator, OrchestratorError
from faultline.validation import ReportValidator, ValidationError


def test_validator_passes_canonical_result() -> None:
    """Validator accepts a correctly formed canonical analysis result."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    validator = ReportValidator()
    assert validator.validate(result) is True


def test_validator_rejects_insufficient_source_groups() -> None:
    """Validator rejects report with fewer than 2 independent source groups."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: filter evidence to single source group
    result.evidence = [obs for obs in result.evidence if obs.source_group.value == "telemetry"]

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Insufficient independent diagnostic sources"):
        validator.validate(result)


def test_validator_rejects_hallucinated_evidence_id_in_conflicts() -> None:
    """Validator rejects report if conflict references an unissued evidence ID."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: inject fake evidence ID
    result.conflicts[0].evidence_ids.append("EV-999")

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="non-existent evidence ID"):
        validator.validate(result)


def test_validator_rejects_modified_ranking_order() -> None:
    """Validator detects if strategy ranking was tampered with or disagrees with Python calculation."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: swap rank 1 and rank 2
    temp = result.strategy_ranking[0]
    result.strategy_ranking[0] = result.strategy_ranking[1]
    result.strategy_ranking[1] = temp

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Strategy ranking mismatch"):
        validator.validate(result)


def test_validator_rejects_unapproved_execution_status() -> None:
    """Validator rejects any report attempting to claim execution succeeded autonomously."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    result.execution.execution_status = "executed"

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Safety boundary violated"):
        validator.validate(result)


def test_validator_rejects_mismatched_execution_command() -> None:
    """Validator rejects a report where suggested_command does not match the winning strategy."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    # Tamper: set suggested_command to an arbitrary or incorrect command
    result.execution.suggested_command = "kubectl delete pod --all"

    validator = ReportValidator()
    with pytest.raises(ValidationError, match="Execution suggested_command mismatch"):
        validator.validate(result)


def test_orchestrator_rejects_fabricated_model_citation() -> None:
    """Orchestrator immediately catches and rejects fabricated EV-999 citations from model."""
    class MaliciousModelProvider(FakeGeminiProvider):
        def synthesise_hypotheses(
            self,
            incident: FaultReport,
            evidence_ledger: list,
            allowed_causes: list,
        ) -> HypothesisDraftSet:
            return HypothesisDraftSet(
                hypotheses=[
                    HypothesisDraft(
                        cause_code=RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
                        summary="Forged citation test",
                        causal_chain=["Forged step"],
                        supporting_evidence_ids=["EV-999"],  # Non-existent ID
                        opposing_evidence_ids=[],
                    ),
                    HypothesisDraft(
                        cause_code=RootCauseCode.TRAFFIC_SURGE,
                        summary="Secondary cause",
                        causal_chain=["Step 1"],
                        supporting_evidence_ids=["EV-001"],
                        opposing_evidence_ids=[],
                    ),
                ]
            )

    orchestrator = IncidentOrchestrator(provider=MaliciousModelProvider())
    with pytest.raises(OrchestratorError, match="Fabricated evidence citations"):
        orchestrator.analyze_scenario("cache_invalidation_lag")


def test_model_shortlist_variation_preserves_deterministic_winner() -> None:
    """Verifies that differing candidate shortlists cannot change the winning repair strategy."""
    class SubsetModelProvider(FakeGeminiProvider):
        def synthesise_hypotheses(
            self,
            incident: FaultReport,
            evidence_ledger: list,
            allowed_causes: list,
        ) -> HypothesisDraftSet:
            # Model shortlists only 2 causes
            return HypothesisDraftSet(
                hypotheses=[
                    HypothesisDraft(
                        cause_code=RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
                        summary="Consumer stalled",
                        causal_chain=["Step A"],
                        supporting_evidence_ids=["EV-001", "EV-002"],
                        opposing_evidence_ids=[],
                    ),
                    HypothesisDraft(
                        cause_code=RootCauseCode.DATABASE_CAPACITY_DEGRADATION,
                        summary="DB degradation",
                        causal_chain=["Step B"],
                        supporting_evidence_ids=["EV-002"],
                        opposing_evidence_ids=["EV-004"],
                    ),
                ]
            )

    orchestrator = IncidentOrchestrator(provider=SubsetModelProvider())
    result = orchestrator.analyze_scenario("cache_invalidation_lag")
    assert result.strategy_ranking[0].strategy_id == "RECOVER_CONSUMER_AND_DRAIN"
    assert result.strategy_ranking[0].rank == 1


def test_scenario_path_traversal_protection() -> None:
    """ScenarioRepository raises ValueError on path traversal attempts."""
    repo = ScenarioRepository()
    with pytest.raises(ValueError, match="Invalid scenario ID format"):
        repo.get_scenario("../policy")


def test_ledger_observation_immutability() -> None:
    """EvidenceObservation is frozen; attempts to mutate fields raise ValidationError."""
    provider = FakeGeminiProvider()
    orchestrator = IncidentOrchestrator(provider=provider)
    result = orchestrator.analyze_scenario("cache_invalidation_lag")

    obs = result.evidence[0]
    with pytest.raises(PydanticValidationError):
        obs.id = "EV-999"  # type: ignore[misc]
