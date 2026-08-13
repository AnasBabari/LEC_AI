"""Unit tests for ReportValidator assertions and safety invariants."""

import pytest
from faultline.gemini import FakeGeminiProvider
from faultline.models import RootCauseCode
from faultline.orchestrator import IncidentOrchestrator
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
