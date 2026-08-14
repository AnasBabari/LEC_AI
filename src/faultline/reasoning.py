"""Deterministic Conflict Detection, Evidence-Strength Scoring, and 4D Strategy Ranking."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from faultline.diagnostics import EvidenceLedger
from faultline.models import (
    ComponentEnum,
    Conflict,
    ConflictType,
    EvaluatedHypothesis,
    EvidenceObservation,
    EvidenceStrengthBand,
    HealthDimension,
    HealthStatus,
    HypothesisDraft,
    ObservationEvidenceScore,
    PolicyConfig,
    RootCauseCode,
    SourceGroup,
    StrategyScore,
)


class PolicyEngine:
    """Loads, validates, and encapsulates scoring rules, cause catalogues, and strategy matrices."""

    def __init__(self, policy_path: Optional[Path] = None) -> None:
        if policy_path is None:
            policy_path = Path(__file__).resolve().parents[2] / "data" / "policy.json"
        with open(policy_path, "r", encoding="utf-8") as f:
            self.policy_data: dict[str, Any] = json.load(f)

        # Validate policy schema at startup
        self.validated_config = PolicyConfig.model_validate(self.policy_data)

        self.scoring_weights = self.policy_data["scoring_weights"]
        self.reliability_weights = self.policy_data["reliability_weights"]
        self.freshness_thresholds = self.policy_data["freshness_thresholds_seconds"]
        self.freshness_weights = self.policy_data["freshness_weights"]
        self.directness_weights = self.policy_data["directness_weights"]
        self.cause_catalogue = self.policy_data["cause_catalogue"]
        self.strategies = self.policy_data["strategies"]

    @property
    def cause_rules(self) -> dict[RootCauseCode, list[dict[str, Any]]]:
        """Map each RootCauseCode to its list of signal rules from the catalogue."""
        result: dict[RootCauseCode, list[dict[str, Any]]] = {}
        for code in RootCauseCode:
            cause_def = self.cause_catalogue.get(code.value, {})
            result[code] = cause_def.get("signal_rules", [])
        return result


class ConflictDetector:
    """Identifies and categorizes diagnostic conflicts across independent source groups."""

    @staticmethod
    def detect_conflicts(ledger: EvidenceLedger) -> list[Conflict]:
        """Classify direct contradictions, scope tensions, and temporal conflicts with strict dimension matching."""
        observations = ledger.get_observations()
        conflicts: list[Conflict] = []
        conflict_idx = 1

        # Group observations by (component, dimension_family)
        # Latency and query efficiency are in the latency/performance family
        def get_dimension_family(dim: HealthDimension) -> str:
            if dim in (HealthDimension.LATENCY, HealthDimension.QUERY_EFFICIENCY):
                return "performance"
            return dim.value

        by_comp_dim: dict[tuple[ComponentEnum, str], list[EvidenceObservation]] = {}
        for obs in observations:
            family = get_dimension_family(obs.dimension)
            by_comp_dim.setdefault((obs.component, family), []).append(obs)

        for (component, _), obs_list in by_comp_dim.items():
            # Compare pairs from DIFFERENT source groups
            for i in range(len(obs_list)):
                for j in range(i + 1, len(obs_list)):
                    obs_a = obs_list[i]
                    obs_b = obs_list[j]

                    if obs_a.source_group == obs_b.source_group:
                        continue

                    conflict = ConflictDetector._evaluate_pair(obs_a, obs_b, conflict_id=f"CONF-{conflict_idx:03d}")
                    if conflict:
                        conflicts.append(conflict)
                        conflict_idx += 1

        return conflicts

    @staticmethod
    def _evaluate_pair(
        obs_a: EvidenceObservation,
        obs_b: EvidenceObservation,
        conflict_id: str,
    ) -> Optional[Conflict]:
        """Evaluate if two observations on the same component and compatible dimension form a reportable conflict."""
        a_is_healthy = obs_a.status == HealthStatus.HEALTHY
        b_is_healthy = obs_b.status == HealthStatus.HEALTHY
        a_is_unhealthy = obs_a.status in (HealthStatus.DEGRADED, HealthStatus.FAILED)
        b_is_unhealthy = obs_b.status in (HealthStatus.DEGRADED, HealthStatus.FAILED)

        # Check for opposing health statuses
        if not ((a_is_healthy and b_is_unhealthy) or (b_is_healthy and a_is_unhealthy)):
            return None

        # Check temporal overlap
        windows_overlap = (obs_a.window_start <= obs_b.window_end) and (obs_b.window_start <= obs_a.window_end)

        if not windows_overlap:
            return Conflict(
                id=conflict_id,
                conflict_type=ConflictType.TEMPORAL_CONFLICT,
                component=obs_a.component,
                evidence_ids=[obs_a.id, obs_b.id],
                headline=f"Temporal Disagreement on {obs_a.component.value}",
                description=(
                    f"{obs_a.source} ({obs_a.source_group.value}) reported {obs_a.status.value} at {obs_a.observed_at.isoformat()} "
                    f"whereas {obs_b.source} ({obs_b.source_group.value}) reported {obs_b.status.value} at {obs_b.observed_at.isoformat()}."
                ),
                operational_implication="Discrepancy is explained by non-overlapping measurement windows; state likely evolved over time.",
            )

        # If overlapping and differing measurement scopes: Scope Tension
        if obs_a.scope != obs_b.scope:
            scopes = {obs_a.scope, obs_b.scope}
            if "synthetic_probe" in scopes and "workload" in scopes:
                headline = f"Scope Tension on {obs_a.component.value}: Workload vs Synthetic Probe"
                op_implication = (
                    "Both observations are accurate within their measurement scopes: the component responds normally to direct synthetic probes, "
                    "but experiences degradation under actual production workload due to upstream or downstream dependencies."
                )
            else:
                headline = f"Scope Tension on {obs_a.component.value}: '{obs_a.scope}' vs '{obs_b.scope}'"
                op_implication = (
                    f"Both observations reflect valid measurements under different operational scopes ('{obs_a.scope}' vs '{obs_b.scope}')."
                )

            return Conflict(
                id=conflict_id,
                conflict_type=ConflictType.SCOPE_TENSION,
                component=obs_a.component,
                evidence_ids=[obs_a.id, obs_b.id],
                headline=headline,
                description=(
                    f"Source '{obs_a.source}' ({obs_a.scope}) reports {obs_a.status.value} ({obs_a.signal}={obs_a.value}{obs_a.unit}), "
                    f"while source '{obs_b.source}' ({obs_b.scope}) reports {obs_b.status.value} ({obs_b.signal}={obs_b.value}{obs_b.unit})."
                ),
                operational_implication=op_implication,
            )

        # Same scope, overlapping window: check exact dimension equality for direct contradiction
        if obs_a.dimension != obs_b.dimension:
            return Conflict(
                id=conflict_id,
                conflict_type=ConflictType.SCOPE_TENSION,
                component=obs_a.component,
                evidence_ids=[obs_a.id, obs_b.id],
                headline=f"Measurement Dimension Tension on {obs_a.component.value}: {obs_a.dimension.value} vs {obs_b.dimension.value}",
                description=(
                    f"Source '{obs_a.source}' reports {obs_a.status.value} on {obs_a.dimension.value} ({obs_a.signal}={obs_a.value}{obs_a.unit}), "
                    f"while source '{obs_b.source}' reports {obs_b.status.value} on {obs_b.dimension.value} ({obs_b.signal}={obs_b.value}{obs_b.unit}) in scope '{obs_a.scope}'."
                ),
                operational_implication=(
                    f"Discrepancy reflects distinct measured health dimensions ({obs_a.dimension.value} vs {obs_b.dimension.value}) within the same component."
                ),
            )

        # Direct contradiction: same scope, same dimension, overlapping window, opposing status
        return Conflict(
            id=conflict_id,
            conflict_type=ConflictType.DIRECT_CONTRADICTION,
            component=obs_a.component,
            evidence_ids=[obs_a.id, obs_b.id],
            headline=f"Direct Contradiction on {obs_a.component.value} ({obs_a.dimension.value})",
            description=(
                f"Source '{obs_a.source}' ({obs_a.source_group.value}) reports {obs_a.status.value} "
                f"while independent source '{obs_b.source}' ({obs_b.source_group.value}) reports {obs_b.status.value} "
                f"over overlapping time windows for {obs_a.dimension.value}."
            ),
            operational_implication="Conflicting signals require corroboration from a third independent source before taking action.",
        )


class EvidenceEvaluator:
    """Deterministically calculates evidence strength, net support, and decision weights."""

    def __init__(self, policy: Optional[PolicyEngine] = None) -> None:
        self.policy = policy or PolicyEngine()

    def evaluate_hypotheses(
        self,
        candidate_codes: list[RootCauseCode],
        ledger: EvidenceLedger,
        draft_hypotheses: Optional[list[HypothesisDraft]] = None,
    ) -> list[EvaluatedHypothesis]:
        """Evaluate evidence strength for candidate root causes against the evidence ledger."""
        observations = ledger.get_observations()
        evaluated: list[EvaluatedHypothesis] = []

        draft_map: dict[RootCauseCode, HypothesisDraft] = {}
        if draft_hypotheses:
            for d in draft_hypotheses:
                draft_map[d.cause_code] = d

        raw_net_scores: dict[RootCauseCode, float] = {}
        temp_evaluations: list[dict[str, Any]] = []

        for code in candidate_codes:
            code_key = code.value
            cause_def = self.policy.cause_catalogue.get(code_key)
            if not cause_def:
                continue

            rules = cause_def.get("signal_rules", [])
            supporting_candidates: list[ObservationEvidenceScore] = []
            opposing_candidates: list[ObservationEvidenceScore] = []

            for obs in observations:
                matched_rule = self._match_rule(obs, rules)
                if not matched_rule:
                    continue

                rel_str = matched_rule["relationship"]
                directness_str = matched_rule["directness"]

                # Calculate strength components
                r_score = self.policy.reliability_weights.get(obs.reliability.value, 1)
                f_score = self._compute_freshness_score(obs.observed_at, ledger.incident_at)
                d_score = self.policy.directness_weights.get(directness_str, 1)
                total_strength = r_score + f_score + d_score

                score_item = ObservationEvidenceScore(
                    evidence_id=obs.id,
                    source_group=obs.source_group,
                    component=obs.component,
                    signal=obs.signal,
                    reliability_score=r_score,
                    freshness_score=f_score,
                    directness_score=d_score,
                    total_strength=total_strength,
                    relationship=rel_str,
                    is_dominant=True,
                    excluded_by_source_cap=False,
                )

                if rel_str == "supports":
                    supporting_candidates.append(score_item)
                elif rel_str == "opposes":
                    opposing_candidates.append(score_item)

            # Apply per-source-group cap
            supporting_scored = self._apply_source_group_cap(supporting_candidates)
            opposing_scored = self._apply_source_group_cap(opposing_candidates)

            # Calculate net evidence
            support_total = sum(s.total_strength for s in supporting_scored if not s.excluded_by_source_cap)
            oppose_total = sum(s.total_strength for s in opposing_scored if not s.excluded_by_source_cap)
            net_score = max(0.0, float(support_total - oppose_total))

            raw_net_scores[code] = net_score

            draft = draft_map.get(code)
            summary_val = draft.summary if draft else cause_def["description"]
            causal_chain_val = (
                draft.causal_chain
                if draft
                else [
                    f"Trigger root cause: {cause_def['name']}",
                    "Cascades through intermediate service layers",
                    "Surfaces as operational latency and connection exhaustion",
                ]
            )
            uncertainties_val = (
                draft.unresolved_uncertainties
                if draft
                else [f"Remaining uncertainty regarding exact propagation dynamics of {cause_def['name']}."]
            )
            contextual_ids_val = draft.contextual_evidence_ids if draft else []

            temp_evaluations.append(
                {
                    "cause_code": code,
                    "name": cause_def["name"],
                    "summary": summary_val,
                    "causal_chain": causal_chain_val,
                    "supporting_observations": supporting_scored,
                    "opposing_observations": opposing_scored,
                    "contextual_evidence_ids": contextual_ids_val,
                    "supporting_score": float(support_total),
                    "opposing_score": float(oppose_total),
                    "net_evidence_score": net_score,
                    "unresolved_uncertainties": uncertainties_val,
                }
            )

        # Calculate decision weights (normalized over positive net scores)
        total_positive_net = sum(raw_net_scores.values())

        for temp in temp_evaluations:
            code = temp["cause_code"]
            net = temp["net_evidence_score"]

            if total_positive_net > 0:
                raw_weight = (net / total_positive_net) * 100.0
                decision_weight = round(raw_weight, 1)
            else:
                decision_weight = 0.0

            # Determine strength band
            distinct_supporting_groups = {
                s.source_group for s in temp["supporting_observations"] if not s.excluded_by_source_cap
            }
            if net >= 12 and len(distinct_supporting_groups) >= 2:
                band = EvidenceStrengthBand.STRONG
            elif net >= 6:
                band = EvidenceStrengthBand.MODERATE
            elif net >= 1:
                band = EvidenceStrengthBand.WEAK
            else:
                band = EvidenceStrengthBand.UNSUPPORTED

            evaluated.append(
                EvaluatedHypothesis(
                    cause_code=code,
                    name=temp["name"],
                    summary=temp["summary"],
                    causal_chain=temp["causal_chain"],
                    supporting_observations=temp["supporting_observations"],
                    opposing_observations=temp["opposing_observations"],
                    contextual_evidence_ids=temp["contextual_evidence_ids"],
                    supporting_score=temp["supporting_score"],
                    opposing_score=temp["opposing_score"],
                    net_evidence_score=net,
                    decision_weight=decision_weight,
                    strength_band=band,
                    unresolved_uncertainties=temp["unresolved_uncertainties"],
                )
            )

        # Sort hypotheses by net evidence score descending
        evaluated.sort(key=lambda h: h.net_evidence_score, reverse=True)
        return evaluated

    def _compute_freshness_score(self, observed_at: datetime, incident_at: datetime) -> int:
        """Compute freshness score anchored to incident timestamp with clock skew protection."""
        if observed_at > incident_at:
            forward_skew = (observed_at - incident_at).total_seconds()
            if forward_skew > 60:
                # Discard or penalize future-dated data
                return self.policy.freshness_weights["stale"]
            diff_seconds = 0.0
        else:
            diff_seconds = (incident_at - observed_at).total_seconds()

        if diff_seconds <= self.policy.freshness_thresholds["current_max"]:
            return self.policy.freshness_weights["current"]
        if diff_seconds <= self.policy.freshness_thresholds["recent_max"]:
            return self.policy.freshness_weights["recent"]
        return self.policy.freshness_weights["stale"]

    def validate_hypothesis_citations(
        self,
        draft: HypothesisDraft,
        observations: list[EvidenceObservation],
    ) -> tuple[bool, list[str]]:
        """Strictly validate that draft citations match policy cause signal rules across all 3 categories.

        1. supporting_evidence_ids:
           - Must exist in current ledger.
           - Must match a policy signal rule for this RootCauseCode with relationship == 'supports'.
           - Non-matching or opposing observations are rejected (must be moved to contextual_evidence_ids or removed).
        2. opposing_evidence_ids:
           - Must exist in current ledger.
           - Must match a policy signal rule for this RootCauseCode with relationship == 'opposes'.
           - Non-matching or supporting observations are rejected.
        3. contextual_evidence_ids:
           - Must exist in current ledger.
           - Provides narrative context without impacting numerical cause scoring.
        4. Invariant:
           - Must have at least 1 verified supporting citation matching a SUPPORTS policy rule.
        """
        obs_map = {obs.id: obs for obs in observations}
        rules = self.policy.cause_rules.get(draft.cause_code, [])
        errors: list[str] = []
        valid_supporting: list[str] = []

        # 1. Validate supporting citations
        for sup_id in draft.supporting_evidence_ids:
            obs = obs_map.get(sup_id)
            if not obs:
                errors.append(f"Non-existent supporting citation '{sup_id}' for {draft.cause_code.value}")
                continue
            matched = self._match_rule(obs, rules)
            if not matched:
                errors.append(
                    f"Observation '{sup_id}' ({obs.component.value}:{obs.signal}) does not match any SUPPORTS rule for {draft.cause_code.value}. Place in contextual_evidence_ids if relevant."
                )
            elif matched.get("relationship") != "supports":
                errors.append(
                    f"Observation '{sup_id}' is an opposing signal for {draft.cause_code.value}, cannot be cited as supporting"
                )
            else:
                valid_supporting.append(sup_id)

        # 2. Validate opposing citations
        for opp_id in draft.opposing_evidence_ids:
            obs = obs_map.get(opp_id)
            if not obs:
                errors.append(f"Non-existent opposing citation '{opp_id}' for {draft.cause_code.value}")
                continue
            matched = self._match_rule(obs, rules)
            if not matched:
                errors.append(
                    f"Observation '{opp_id}' ({obs.component.value}:{obs.signal}) does not match any OPPOSES rule for {draft.cause_code.value}"
                )
            elif matched.get("relationship") != "opposes":
                errors.append(
                    f"Observation '{opp_id}' is a supporting signal for {draft.cause_code.value}, cannot be cited as opposing"
                )

        # 3. Validate contextual citations (must exist in ledger and NOT match causal rules for this cause)
        for ctx_id in draft.contextual_evidence_ids:
            obs = obs_map.get(ctx_id)
            if not obs:
                errors.append(f"Non-existent contextual citation '{ctx_id}' for {draft.cause_code.value}")
                continue
            matched = self._match_rule(obs, rules)
            if matched:
                rel = matched.get("relationship", "causal")
                errors.append(
                    f"Observation '{ctx_id}' ({obs.component.value}:{obs.signal}) matches a direct {rel.upper()} rule for {draft.cause_code.value}. "
                    f"It must be placed in {rel}ing_evidence_ids rather than contextual_evidence_ids."
                )

        # 4. Require at least one verified supporting citation
        if not valid_supporting and not errors:
            errors.append(f"Hypothesis {draft.cause_code.value} lacks any matching supporting signal rule citations")

        return (len(errors) == 0, errors)

    def _match_rule(
        self,
        obs: EvidenceObservation,
        rules: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """Match an observation against cause signal rules."""
        for rule in rules:
            if rule["component"] != obs.component.value:
                continue
            if rule["dimension"] != obs.dimension.value:
                continue
            if obs.status.value not in rule.get("statuses", []):
                continue
            if "scope" in rule and rule["scope"] != obs.scope:
                continue
            return rule
        return None

    def _apply_source_group_cap(
        self,
        candidates: list[ObservationEvidenceScore],
    ) -> list[ObservationEvidenceScore]:
        """Select the strongest observation per source group to count numerically; cap remaining."""
        if not candidates:
            return []

        # Find max strength per source group
        by_group: dict[SourceGroup, list[ObservationEvidenceScore]] = {}
        for item in candidates:
            by_group.setdefault(item.source_group, []).append(item)

        result: list[ObservationEvidenceScore] = []
        for _, items in by_group.items():
            # Sort descending by total_strength
            sorted_items = sorted(items, key=lambda x: x.total_strength, reverse=True)
            for idx, item in enumerate(sorted_items):
                is_excluded = idx > 0
                result.append(
                    ObservationEvidenceScore(
                        evidence_id=item.evidence_id,
                        source_group=item.source_group,
                        component=item.component,
                        signal=item.signal,
                        reliability_score=item.reliability_score,
                        freshness_score=item.freshness_score,
                        directness_score=item.directness_score,
                        total_strength=item.total_strength,
                        relationship=item.relationship,
                        is_dominant=not is_excluded,
                        excluded_by_source_cap=is_excluded,
                    )
                )

        return result


class StrategyRanker:
    """Evaluates and ranks repair strategies using 4-dimensional scoring and deterministic tie-breaking."""

    def __init__(self, policy: PolicyEngine) -> None:
        self.policy = policy

    def rank_strategies(
        self,
        evaluated_hypotheses: list[EvaluatedHypothesis],
    ) -> list[StrategyScore]:
        """Rank strategies based on causal expected impact, safety, speed, and affordability using full precision."""
        weights = self.policy.scoring_weights
        w_impact = weights["impact"]
        w_safety = weights["safety"]
        w_speed = weights["speed"]
        w_affordability = weights["affordability"]

        # Map cause decision weights (0.0 - 1.0)
        # Use full precision net evidence ratio if available
        total_pos_net = sum(h.net_evidence_score for h in evaluated_hypotheses if h.net_evidence_score > 0)
        cause_weights: dict[str, float] = {}
        for h in evaluated_hypotheses:
            if total_pos_net > 0 and h.net_evidence_score > 0:
                cause_weights[h.cause_code.value] = h.net_evidence_score / total_pos_net
            else:
                cause_weights[h.cause_code.value] = 0.0

        intermediate: list[tuple[float, float, float, float, str, dict[str, Any]]] = []

        for strat_id, strat_def in self.policy.strategies.items():
            eff_map = strat_def.get("effectiveness_by_cause", {})

            # Expected Impact = sum(cause_weight * effectiveness)
            expected_impact = 0.0
            for cause_val, eff in eff_map.items():
                w = cause_weights.get(cause_val, 0.0)
                expected_impact += w * float(eff)

            safety = float(strat_def["safety"])
            speed = float(strat_def["speed"])
            affordability = float(strat_def["affordability"])

            final_score = (
                (w_impact * expected_impact)
                + (w_safety * safety)
                + (w_speed * speed)
                + (w_affordability * affordability)
            )

            intermediate.append(
                (
                    final_score,
                    expected_impact,
                    safety,
                    speed,
                    strat_id,
                    strat_def,
                )
            )

        # Deterministic sorting using full-precision unrounded floats:
        # 1. Higher unrounded final_score
        # 2. Higher unrounded expected_impact
        # 3. Higher unrounded safety
        # 4. Higher unrounded speed
        # 5. Lexicographically smaller strategy_id
        intermediate.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2],
                -item[3],
                item[4],
            )
        )

        scores: list[StrategyScore] = []
        for rank_idx, (f_score, exp_impact, s_safety, s_speed, strat_id, strat_def) in enumerate(intermediate, start=1):
            scores.append(
                StrategyScore(
                    strategy_id=strat_id,
                    name=strat_def["name"],
                    description=strat_def["description"],
                    expected_impact=round(exp_impact, 2),
                    safety=round(s_safety, 2),
                    speed=round(s_speed, 2),
                    affordability=round(float(strat_def["affordability"]), 2),
                    final_score=round(f_score, 2),
                    rank=rank_idx,
                    risk_notes=strat_def["risk_notes"],
                    reversibility=strat_def["reversibility"],
                    suggested_command=strat_def.get("suggested_command"),
                    preconditions=strat_def.get("preconditions", []),
                )
            )

        return scores
