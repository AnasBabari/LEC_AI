"""Strict validation of incident analysis reports, invariants, and safety boundaries."""

import logging
from datetime import datetime, timezone
from typing import Optional

from faultline.diagnostics import EvidenceLedger
from faultline.models import (
    AdvantageDimension,
    AnalysisResult,
    LifecycleState,
    RootCauseCode,
    ValidationError,
)
from faultline.reasoning import (
    ConflictDetector,
    EvidenceEvaluator,
    PolicyEngine,
    StrategyRanker,
)

logger = logging.getLogger(__name__)


class ReportValidator:
    """Strict validator asserting report integrity, evidence provenance, and deterministic decision authority."""

    def __init__(self, policy: Optional[PolicyEngine] = None) -> None:
        self.policy = policy or PolicyEngine()
        self.ranker = StrategyRanker(self.policy)
        self.evaluator = EvidenceEvaluator(self.policy)

    def validate(self, result: AnalysisResult) -> bool:
        """Validate complete AnalysisResult against all domain, deterministic authority, and safety invariants."""
        # 1. Check lifecycle state (REPORTING is not an acceptable terminal or validation state)
        if result.state not in (LifecycleState.VALIDATED, LifecycleState.VALIDATING):
            raise ValidationError(f"Invalid terminal lifecycle state: {result.state}")

        # 2. Check independent source group coverage (minimum 2 independent groups)
        observed_source_groups = {obs.source_group for obs in result.evidence}
        if len(observed_source_groups) < 2:
            raise ValidationError(
                f"Insufficient independent diagnostic sources: found {len(observed_source_groups)} "
                f"({[g.value for g in observed_source_groups]}), minimum required is 2."
            )

        # 3. Strict Sequential Evidence ID & Ledger Reconstruction (Finding 10)
        if not result.evidence:
            raise ValidationError("Evidence ledger in report is empty.")

        reported_at_str = result.incident.get("reported_at")
        if reported_at_str:
            t0 = datetime.fromisoformat(reported_at_str.replace("Z", "+00:00"))
        else:
            t0 = datetime.now(timezone.utc)

        try:
            reconstructed_ledger = EvidenceLedger.from_validated_snapshot(result.evidence, incident_at=t0)
        except ValueError as snap_err:
            raise ValidationError(f"Evidence ledger integrity violation: {snap_err}") from snap_err

        evidence_ids = [obs.id for obs in result.evidence]
        ledger_id_set = set(evidence_ids)

        # 4. Recompute and Validate All Conflicts from Reconstructed Ledger (Finding 11)
        expected_conflicts = ConflictDetector.detect_conflicts(reconstructed_ledger)
        if not result.conflicts:
            raise ValidationError("At least one diagnostic conflict or scope tension must be identified and analyzed.")

        if len(result.conflicts) != len(expected_conflicts):
            raise ValidationError(
                f"Conflict count mismatch: report contains {len(result.conflicts)}, "
                f"authoritative recomputation detected {len(expected_conflicts)}."
            )

        for actual_conf, exp_conf in zip(result.conflicts, expected_conflicts):
            if actual_conf.id != exp_conf.id:
                raise ValidationError(f"Conflict ID mismatch: '{actual_conf.id}' vs expected '{exp_conf.id}'.")
            if actual_conf.conflict_type != exp_conf.conflict_type:
                raise ValidationError(
                    f"Conflict type mismatch on {actual_conf.id}: '{actual_conf.conflict_type.value}' vs expected '{exp_conf.conflict_type.value}'."
                )
            if actual_conf.component != exp_conf.component:
                raise ValidationError(
                    f"Conflict component mismatch on {actual_conf.id}: '{actual_conf.component.value}' vs expected '{exp_conf.component.value}'."
                )
            if actual_conf.evidence_ids != exp_conf.evidence_ids:
                raise ValidationError(
                    f"Conflict evidence citations mismatch on {actual_conf.id}: {actual_conf.evidence_ids} vs expected {exp_conf.evidence_ids}."
                )

            for cited_id in actual_conf.evidence_ids:
                if cited_id not in ledger_id_set:
                    raise ValidationError(f"Conflict {actual_conf.id} cites non-existent evidence ID: {cited_id}")

            cited_obs = [obs for obs in result.evidence if obs.id in actual_conf.evidence_ids]
            cited_groups = {obs.source_group for obs in cited_obs}
            if len(cited_groups) < 2:
                raise ValidationError(f"Conflict {actual_conf.id} does not span independent source groups: {cited_groups}")

        # 5. Deterministic Reconstruction of Hypotheses from Evidence Ledger & Policy (Finding 12)
        authoritative_hypotheses = self.evaluator.evaluate_hypotheses(
            candidate_codes=list(RootCauseCode),
            ledger=reconstructed_ledger,
        )
        auth_hyp_by_code = {h.cause_code: h for h in authoritative_hypotheses}

        if len(result.hypotheses) < 2:
            raise ValidationError(
                f"Analysis report must contain at least 2 evaluated hypotheses, found {len(result.hypotheses)}."
            )

        allowed_cause_values = {c.value for c in RootCauseCode}
        has_positive_evidence = False

        for hyp in result.hypotheses:
            if hyp.cause_code.value not in allowed_cause_values:
                raise ValidationError(f"Hypothesis contains unapproved cause code: {hyp.cause_code}")

            auth_hyp = auth_hyp_by_code.get(hyp.cause_code)
            if not auth_hyp:
                raise ValidationError(f"Hypothesis {hyp.cause_code.value} is not authorized by policy catalogue.")

            # Assert exact score match against authoritative evaluation
            if abs(hyp.supporting_score - auth_hyp.supporting_score) > 0.05:
                raise ValidationError(
                    f"Hypothesis {hyp.cause_code.value} supporting_score mismatch: reported {hyp.supporting_score}, "
                    f"expected authoritative score {auth_hyp.supporting_score}."
                )
            if abs(hyp.opposing_score - auth_hyp.opposing_score) > 0.05:
                raise ValidationError(
                    f"Hypothesis {hyp.cause_code.value} opposing_score mismatch: reported {hyp.opposing_score}, "
                    f"expected authoritative score {auth_hyp.opposing_score}."
                )
            if abs(hyp.net_evidence_score - auth_hyp.net_evidence_score) > 0.05:
                raise ValidationError(
                    f"Hypothesis {hyp.cause_code.value} net_evidence_score mismatch: reported {hyp.net_evidence_score}, "
                    f"expected authoritative score {auth_hyp.net_evidence_score}."
                )
            if abs(hyp.decision_weight - auth_hyp.decision_weight) > 0.1:
                raise ValidationError(
                    f"Hypothesis {hyp.cause_code.value} decision_weight mismatch: reported {hyp.decision_weight}%, "
                    f"expected authoritative weight {auth_hyp.decision_weight}%."
                )
            if hyp.strength_band != auth_hyp.strength_band:
                raise ValidationError(
                    f"Hypothesis {hyp.cause_code.value} strength_band mismatch: reported '{hyp.strength_band.value}', "
                    f"expected authoritative band '{auth_hyp.strength_band.value}'."
                )

            if hyp.net_evidence_score > 0:
                has_positive_evidence = True

            # Verify observation breakdown match (Finding 12 & Finding 27: complete set comparison)
            if len(hyp.supporting_observations) != len(auth_hyp.supporting_observations):
                raise ValidationError(
                    f"Hypothesis {hyp.cause_code.value} supporting observations count mismatch: "
                    f"reported {len(hyp.supporting_observations)}, expected {len(auth_hyp.supporting_observations)}."
                )
            auth_sup_by_id = {s.evidence_id: s for s in auth_hyp.supporting_observations}
            for obs_score in hyp.supporting_observations:
                if obs_score.evidence_id not in auth_sup_by_id:
                    raise ValidationError(
                        f"Hypothesis {hyp.cause_code.value} reports unexpected supporting evidence {obs_score.evidence_id}."
                    )
                auth_score = auth_sup_by_id[obs_score.evidence_id]
                if (
                    obs_score.reliability_score != auth_score.reliability_score
                    or obs_score.freshness_score != auth_score.freshness_score
                    or obs_score.directness_score != auth_score.directness_score
                    or obs_score.total_strength != auth_score.total_strength
                    or obs_score.relationship != auth_score.relationship
                    or obs_score.is_dominant != auth_score.is_dominant
                    or obs_score.excluded_by_source_cap != auth_score.excluded_by_source_cap
                ):
                    raise ValidationError(
                        f"Observation breakdown score mismatch for evidence {obs_score.evidence_id} in {hyp.cause_code.value}."
                    )

            if len(hyp.opposing_observations) != len(auth_hyp.opposing_observations):
                raise ValidationError(
                    f"Hypothesis {hyp.cause_code.value} opposing observations count mismatch: "
                    f"reported {len(hyp.opposing_observations)}, expected {len(auth_hyp.opposing_observations)}."
                )
            auth_opp_by_id = {s.evidence_id: s for s in auth_hyp.opposing_observations}
            for obs_score in hyp.opposing_observations:
                if obs_score.evidence_id not in auth_opp_by_id:
                    raise ValidationError(
                        f"Hypothesis {hyp.cause_code.value} reports unexpected opposing evidence {obs_score.evidence_id}."
                    )
                auth_score = auth_opp_by_id[obs_score.evidence_id]
                if (
                    obs_score.reliability_score != auth_score.reliability_score
                    or obs_score.freshness_score != auth_score.freshness_score
                    or obs_score.directness_score != auth_score.directness_score
                    or obs_score.total_strength != auth_score.total_strength
                    or obs_score.relationship != auth_score.relationship
                    or obs_score.is_dominant != auth_score.is_dominant
                    or obs_score.excluded_by_source_cap != auth_score.excluded_by_source_cap
                ):
                    raise ValidationError(
                        f"Observation breakdown score mismatch for opposing evidence {obs_score.evidence_id} in {hyp.cause_code.value}."
                    )

            # Verify contextual citations exist in ledger and do NOT match causal scoring rules
            cause_rules = self.policy.cause_rules.get(hyp.cause_code, [])
            for ctx_id in hyp.contextual_evidence_ids:
                if ctx_id not in ledger_id_set:
                    raise ValidationError(
                        f"Hypothesis {hyp.cause_code.value} cites non-existent contextual evidence ID: {ctx_id}"
                    )
                ctx_obs = reconstructed_ledger.get_by_id(ctx_id)
                if ctx_obs and self.evaluator._match_rule(ctx_obs, cause_rules):
                    raise ValidationError(
                        f"Hypothesis {hyp.cause_code.value} cites causal evidence '{ctx_id}' as contextual."
                    )

        if not has_positive_evidence:
            raise ValidationError("No hypothesis has positive net evidence score; insufficient causal basis.")

        # 6. Recompute Strategy Ranking from Reconstructed Hypotheses (Deterministic Authority)
        expected_ranking = self.ranker.rank_strategies(authoritative_hypotheses)
        if len(result.strategy_ranking) != len(expected_ranking):
            raise ValidationError(
                f"Strategy ranking count does not match policy catalogue: reported {len(result.strategy_ranking)}, "
                f"expected {len(expected_ranking)}."
            )

        for idx, (actual, expected) in enumerate(zip(result.strategy_ranking, expected_ranking)):
            if actual.strategy_id != expected.strategy_id:
                raise ValidationError(
                    f"Strategy ranking mismatch at position {idx + 1}: reported '{actual.strategy_id}', "
                    f"expected authoritative strategy '{expected.strategy_id}'."
                )
            if abs(actual.final_score - expected.final_score) > 0.05:
                raise ValidationError(
                    f"Strategy score mismatch for {actual.strategy_id}: reported {actual.final_score}, "
                    f"expected authoritative score {expected.final_score}."
                )
            if abs(actual.expected_impact - expected.expected_impact) > 0.05:
                raise ValidationError(
                    f"Strategy impact score mismatch for {actual.strategy_id}: reported {actual.expected_impact}, "
                    f"expected {expected.expected_impact}."
                )
            if actual.rank != (idx + 1):
                raise ValidationError(
                    f"Strategy {actual.strategy_id} rank field is inconsistent: {actual.rank} vs {idx + 1}"
                )

        # 7. Check recommendation consistency & mandatory structured semantic grounding
        top_strategy = expected_ranking[0]
        rec = result.recommendation

        if rec.winning_strategy_id != top_strategy.strategy_id:
            raise ValidationError(
                f"Recommendation winner mismatch: explanation recommends '{rec.winning_strategy_id}', "
                f"but authoritative rank #1 strategy is '{top_strategy.strategy_id}'."
            )

        # Grounding: Executive summary must reference the winning strategy
        exec_summary_lower = rec.executive_summary.lower()
        if (
            top_strategy.name.lower() not in exec_summary_lower
            and top_strategy.strategy_id.lower() not in exec_summary_lower
        ):
            raise ValidationError(
                f"Executive summary lacks grounding: does not mention winning strategy '{top_strategy.name}'."
            )

        # Check alternative strategy comparison against authoritative ranking
        alt_id = rec.trade_off_comparison.alternative_strategy_id
        if alt_id == top_strategy.strategy_id:
            raise ValidationError("Trade-off comparison must compare winner against a distinct alternative.")

        alt_strategy = next((s for s in expected_ranking if s.strategy_id == alt_id), None)
        if not alt_strategy:
            raise ValidationError(f"Trade-off comparison cites unknown alternative strategy: {alt_id}")

        # Mandatory Structured Grounding Verification
        g = rec.grounding
        if not g:
            raise ValidationError("Report lacks mandatory StructuredDecisionGrounding.")

        if g.winning_strategy_id != top_strategy.strategy_id:
            raise ValidationError(
                f"Structured grounding winning strategy mismatch: '{g.winning_strategy_id}' vs authoritative winner '{top_strategy.strategy_id}'."
            )
        if g.winning_strategy_name != top_strategy.name:
            raise ValidationError(
                f"Structured grounding winning strategy name mismatch: '{g.winning_strategy_name}' vs '{top_strategy.name}'."
            )
        if g.top_cause_code != authoritative_hypotheses[0].cause_code:
            raise ValidationError(
                f"Structured grounding top cause code mismatch: '{g.top_cause_code.value}' vs authoritative top cause '{authoritative_hypotheses[0].cause_code.value}'."
            )

        expected_conflict_ids = [c.id for c in result.conflicts]
        if g.reconciled_conflict_ids != expected_conflict_ids:
            raise ValidationError(
                f"Structured grounding reconciled conflicts mismatch: {g.reconciled_conflict_ids} vs {expected_conflict_ids}."
            )

        expected_conflict_ev_ids = [eid for c in result.conflicts for eid in c.evidence_ids]
        if g.reconciled_evidence_ids != expected_conflict_ev_ids:
            raise ValidationError(
                f"Structured grounding reconciled evidence IDs mismatch: {g.reconciled_evidence_ids} vs {expected_conflict_ev_ids}."
            )

        # Validate structured narrative references (Finding 29)
        for ref_cid in g.referenced_conflict_ids:
            if ref_cid not in expected_conflict_ids:
                raise ValidationError(f"Structured grounding references non-existent conflict ID: {ref_cid}")

        for ref_eid in g.referenced_evidence_ids:
            if ref_eid not in ledger_id_set:
                raise ValidationError(f"Structured grounding references non-existent evidence ID: {ref_eid}")

        if expected_conflict_ids and not g.referenced_conflict_ids:
            raise ValidationError("Structured grounding narrative must reference at least one genuine conflict when conflicts exist.")

        if g.alternative_strategy_id != alt_strategy.strategy_id:
            raise ValidationError(
                f"Structured grounding alternative strategy mismatch: '{g.alternative_strategy_id}' vs '{alt_strategy.strategy_id}'."
            )
        if g.alternative_strategy_name != alt_strategy.name:
            raise ValidationError(
                f"Structured grounding alternative strategy name mismatch: '{g.alternative_strategy_name}' vs '{alt_strategy.name}'."
            )

        # Validate Advantage Dimension and Values
        if g.alternative_advantage_dimension == AdvantageDimension.SPEED:
            if alt_strategy.speed <= top_strategy.speed:
                raise ValidationError(
                    f"Structured grounding claims speed advantage ({alt_strategy.speed}) for alternative, "
                    f"but winner has equal or higher speed ({top_strategy.speed})."
                )
            if (
                abs(g.alternative_advantage_value - alt_strategy.speed) > 0.05
                or abs(g.winning_advantage_value - top_strategy.speed) > 0.05
            ):
                raise ValidationError(
                    "Structured grounding speed advantage values do not match authoritative strategy metrics."
                )
        elif g.alternative_advantage_dimension == AdvantageDimension.AFFORDABILITY:
            if alt_strategy.affordability <= top_strategy.affordability:
                raise ValidationError(
                    f"Structured grounding claims affordability advantage ({alt_strategy.affordability}) for alternative, "
                    f"but winner has equal or higher affordability ({top_strategy.affordability})."
                )
            if (
                abs(g.alternative_advantage_value - alt_strategy.affordability) > 0.05
                or abs(g.winning_advantage_value - top_strategy.affordability) > 0.05
            ):
                raise ValidationError(
                    "Structured grounding affordability advantage values do not match authoritative strategy metrics."
                )
        elif g.alternative_advantage_dimension == AdvantageDimension.SAFETY:
            if alt_strategy.safety <= top_strategy.safety:
                raise ValidationError(
                    f"Structured grounding claims safety advantage ({alt_strategy.safety}) for alternative, "
                    f"but winner has equal or higher safety ({top_strategy.safety})."
                )
            if (
                abs(g.alternative_advantage_value - alt_strategy.safety) > 0.05
                or abs(g.winning_advantage_value - top_strategy.safety) > 0.05
            ):
                raise ValidationError(
                    "Structured grounding safety advantage values do not match authoritative strategy metrics."
                )
        elif g.alternative_advantage_dimension == AdvantageDimension.NONE:
            if (
                alt_strategy.speed > top_strategy.speed
                or alt_strategy.affordability > top_strategy.affordability
                or alt_strategy.safety > top_strategy.safety
            ):
                raise ValidationError("Structured grounding claims no advantage, but alternative outperforms winner.")

        expected_risk = alt_strategy.risk_notes or "Operational risk"
        if g.rejection_risk_factor != expected_risk:
            raise ValidationError(
                f"Structured grounding rejection risk factor mismatch: reported '{g.rejection_risk_factor}', expected '{expected_risk}'."
            )

        # Simplified prose checks (Finding 13): Require non-empty, substantive explanations
        rejection_words = rec.trade_off_comparison.rejection_rationale.strip().split()
        if len(rejection_words) < 8:
            raise ValidationError("Trade-off rejection rationale is too brief to provide defensible justification.")

        contradiction_text = rec.grounded_contradiction_analysis.strip()
        if len(contradiction_text.split()) < 8:
            raise ValidationError("Grounded contradiction analysis is missing or insufficiently detailed.")

        # Grounding check: ensure narrative mentions at least one component, conflict ID, or evidence ID
        detected_conflict_ids = {c.id.lower() for c in result.conflicts}
        detected_evidence_ids = {eid.lower() for c in result.conflicts for eid in c.evidence_ids}
        detected_components = {c.component.value.lower() for c in result.conflicts}
        contra_lower = contradiction_text.lower()
        has_id_ref = any(cid in contra_lower for cid in detected_conflict_ids | detected_evidence_ids)
        has_comp_ref = any(comp in contra_lower for comp in detected_components)

        if not (has_id_ref or has_comp_ref):
            raise ValidationError(
                "Contradiction analysis does not reference any affected components, evidence IDs, or conflict IDs."
            )

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
                f"Execution command mismatch: reported '{result.execution.suggested_command}', "
                f"expected '{expected_cmd}' for strategy {top_strategy.strategy_id}."
            )

        return True
