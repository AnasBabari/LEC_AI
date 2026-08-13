"""Strict validation of incident analysis reports, invariants, and safety boundaries."""

import logging
from typing import Optional

from faultline.models import (
    AnalysisResult,
    LifecycleState,
    RootCauseCode,
)
from faultline.reasoning import PolicyEngine, StrategyRanker

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when an incident report violates safety, provenance, or consistency invariants."""
    pass


class ReportValidator:
    """Strict validator asserting report integrity, evidence provenance, and decision consistency."""

    def __init__(self, policy: Optional[PolicyEngine] = None) -> None:
        self.policy = policy or PolicyEngine()
        self.ranker = StrategyRanker(self.policy)

    def validate(self, result: AnalysisResult) -> bool:
        """Validate complete AnalysisResult against all domain and safety invariants."""
        # 1. Check lifecycle state
        if result.state not in (LifecycleState.VALIDATED, LifecycleState.REPORTING, LifecycleState.VALIDATING):
            raise ValidationError(f"Invalid terminal lifecycle state: {result.state}")

        # 2. Check independent source group coverage (minimum 2 independent groups)
        observed_source_groups = {obs.source_group for obs in result.evidence}
        if len(observed_source_groups) < 2:
            raise ValidationError(
                f"Insufficient independent diagnostic sources: found {len(observed_source_groups)} "
                f"({[g.value for g in observed_source_groups]}), minimum required is 2."
            )

        # 3. Check evidence ID integrity and uniqueness
        evidence_ids = [obs.id for obs in result.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValidationError("Duplicate evidence IDs found in evidence ledger.")
        for eid in evidence_ids:
            if not eid.startswith("EV-"):
                raise ValidationError(f"Malformed evidence ID: {eid}")

        ledger_id_set = set(evidence_ids)

        # 4. Check conflict citations and cross-source requirement
        if not result.conflicts:
            raise ValidationError("At least one diagnostic conflict or scope tension must be identified and analyzed.")

        for conflict in result.conflicts:
            if not conflict.evidence_ids:
                raise ValidationError(f"Conflict {conflict.id} has empty evidence citations.")
            for cited_id in conflict.evidence_ids:
                if cited_id not in ledger_id_set:
                    raise ValidationError(f"Conflict {conflict.id} cites non-existent evidence ID: {cited_id}")

            # Verify cited evidence spans multiple source groups
            cited_obs = [obs for obs in result.evidence if obs.id in conflict.evidence_ids]
            cited_groups = {obs.source_group for obs in cited_obs}
            if len(cited_groups) < 2:
                raise ValidationError(
                    f"Conflict {conflict.id} does not span independent source groups: {cited_groups}"
                )

        # 5. Check hypotheses validity and closed catalogue compliance
        allowed_cause_values = {c.value for c in RootCauseCode}
        if not result.hypotheses:
            raise ValidationError("Analysis report contains no evaluated hypotheses.")

        has_positive_evidence = False
        for hyp in result.hypotheses:
            if hyp.cause_code.value not in allowed_cause_values:
                raise ValidationError(f"Hypothesis contains unapproved cause code: {hyp.cause_code}")

            if hyp.net_evidence_score > 0:
                has_positive_evidence = True

            # Verify all observation citations exist in ledger
            for obs_score in hyp.supporting_observations + hyp.opposing_observations:
                if obs_score.evidence_id not in ledger_id_set:
                    raise ValidationError(
                        f"Hypothesis {hyp.cause_code.value} cites invalid evidence ID: {obs_score.evidence_id}"
                    )

        if not has_positive_evidence:
            raise ValidationError("No hypothesis has positive net evidence score; insufficient causal basis.")

        # 6. Check strategy ranking (minimum 3 strategies, deterministic recomputation check)
        if len(result.strategy_ranking) < 3:
            raise ValidationError(
                f"Insufficient competing repair strategies: found {len(result.strategy_ranking)}, minimum required is 3."
            )

        # Recompute ranking deterministically to assert Python authority
        expected_ranking = self.ranker.rank_strategies(result.hypotheses)
        if len(result.strategy_ranking) != len(expected_ranking):
            raise ValidationError("Strategy ranking count does not match policy catalogue.")

        for idx, (actual, expected) in enumerate(zip(result.strategy_ranking, expected_ranking)):
            if actual.strategy_id != expected.strategy_id:
                raise ValidationError(
                    f"Strategy ranking mismatch at position {idx+1}: reported '{actual.strategy_id}', "
                    f"expected '{expected.strategy_id}'."
                )
            if abs(actual.final_score - expected.final_score) > 0.05:
                raise ValidationError(
                    f"Strategy score mismatch for {actual.strategy_id}: reported {actual.final_score}, "
                    f"expected {expected.final_score}."
                )
            if actual.rank != (idx + 1):
                raise ValidationError(f"Strategy {actual.strategy_id} rank field is inconsistent: {actual.rank} vs {idx+1}")

        # 7. Check recommendation consistency & semantic grounding
        top_strategy = result.strategy_ranking[0]
        rec = result.recommendation

        if rec.winning_strategy_id != top_strategy.strategy_id:
            raise ValidationError(
                f"Recommendation winner mismatch: explanation recommends '{rec.winning_strategy_id}', "
                f"but rank #1 strategy is '{top_strategy.strategy_id}'."
            )

        # Grounding: Executive summary must reference the winning strategy or top cause
        exec_summary_lower = rec.executive_summary.lower()
        if (
            top_strategy.name.lower() not in exec_summary_lower
            and top_strategy.strategy_id.lower() not in exec_summary_lower
        ):
            raise ValidationError(
                f"Executive summary lacks grounding: does not mention winning strategy '{top_strategy.name}'."
            )

        # Check alternative strategy comparison
        alt_id = rec.trade_off_comparison.alternative_strategy_id
        if alt_id == top_strategy.strategy_id:
            raise ValidationError("Trade-off comparison must compare winner against a distinct alternative.")

        alt_strategy = next((s for s in result.strategy_ranking if s.strategy_id == alt_id), None)
        if not alt_strategy:
            raise ValidationError(f"Trade-off comparison cites unknown alternative strategy: {alt_id}")

        # Grounding: Rejection rationale must articulate why the alternative is unsuitable
        rejection_lower = rec.trade_off_comparison.rejection_rationale.lower()
        if len(rejection_lower.split()) < 8:
            raise ValidationError("Trade-off rejection rationale is too brief to provide defensible justification.")

        # Grounding: Contradiction analysis must reference detected conflicts or conflicting evidence
        contradiction_text = rec.grounded_contradiction_analysis
        if not contradiction_text or len(contradiction_text.split()) < 10:
            raise ValidationError("Grounded contradiction analysis is missing or insufficiently detailed.")

        # Verify that contradiction analysis references actual conflict IDs, evidence IDs, or domain scopes
        detected_conflict_ids = {c.id.lower() for c in result.conflicts}
        detected_evidence_ids = {eid.lower() for c in result.conflicts for eid in c.evidence_ids}
        detected_components = {c.component.value.lower() for c in result.conflicts}

        contra_lower = contradiction_text.lower()
        has_id_ref = any(cid in contra_lower for cid in detected_conflict_ids | detected_evidence_ids)
        has_component_scope_ref = any(comp in contra_lower for comp in detected_components) and (
            "probe" in contra_lower
            or "synthetic" in contra_lower
            or "telemetry" in contra_lower
            or "workload" in contra_lower
            or "latency" in contra_lower
            or "scope" in contra_lower
            or "healthy" in contra_lower
            or "tension" in contra_lower
            or "conflict" in contra_lower
        )

        if not (has_id_ref or has_component_scope_ref):
            raise ValidationError(
                "Contradiction analysis is not semantically grounded in detected conflicts or conflicting diagnostic evidence."
            )

        # Check for ungrounded denials of observed contradictions
        denial_phrases = ["no contradiction", "no conflict", "contradictions do not exist", "aliens"]
        if any(dp in contra_lower for dp in denial_phrases):
            raise ValidationError("Contradiction analysis contains ungrounded denial of verified diagnostic conflicts.")

        # 8. Check execution safety boundary
        if result.execution.execution_status != "not_executed":
            raise ValidationError(
                f"Safety boundary violated: execution_status is '{result.execution.execution_status}', "
                "must be 'not_executed'."
            )

        if not result.execution.operator_approval_required:
            raise ValidationError("Safety boundary violated: operator_approval_required must be True.")

        winning_strat_def = self.policy.strategies.get(top_strategy.strategy_id, {})
        expected_cmd = winning_strat_def.get("suggested_command")
        if expected_cmd and result.execution.suggested_command != expected_cmd:
            raise ValidationError(
                f"Execution suggested_command mismatch: expected command for '{top_strategy.strategy_id}', "
                f"got '{result.execution.suggested_command}'."
            )

        return True
