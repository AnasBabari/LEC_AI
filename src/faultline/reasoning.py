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
    HealthStatus,
    HypothesisDraft,
    ObservationEvidenceScore,
    RootCauseCode,
    SourceGroup,
    StrategyScore,
)


class PolicyEngine:
    """Loads and encapsulates scoring rules, cause catalogues, and strategy matrices."""

    def __init__(self, policy_path: Optional[Path] = None) -> None:
        if policy_path is None:
            policy_path = Path(__file__).resolve().parents[2] / "data" / "policy.json"
        with open(policy_path, "r", encoding="utf-8") as f:
            self.policy_data: dict[str, Any] = json.load(f)

        self.scoring_weights = self.policy_data["scoring_weights"]
        self.reliability_weights = self.policy_data["reliability_weights"]
        self.freshness_thresholds = self.policy_data["freshness_thresholds_seconds"]
        self.freshness_weights = self.policy_data["freshness_weights"]
        self.directness_weights = self.policy_data["directness_weights"]
        self.cause_catalogue = self.policy_data["cause_catalogue"]
        self.strategies = self.policy_data["strategies"]


class ConflictDetector:
    """Identifies and categorizes diagnostic conflicts across independent source groups."""

    @staticmethod
    def detect_conflicts(ledger: EvidenceLedger) -> list[Conflict]:
        """Classify direct contradictions, scope tensions, and temporal conflicts."""
        observations = ledger.get_observations()
        conflicts: list[Conflict] = []
        conflict_idx = 1

        # Group observations by component
        by_component: dict[ComponentEnum, list[EvidenceObservation]] = {}
        for obs in observations:
            by_component.setdefault(obs.component, []).append(obs)

        for component, obs_list in by_component.items():
            # Compare pairs from DIFFERENT source groups
            for i in range(len(obs_list)):
                for j in range(i + 1, len(obs_list)):
                    obs_a = obs_list[i]
                    obs_b = obs_list[j]

                    if obs_a.source_group == obs_b.source_group:
                        continue

                    conflict = ConflictDetector._evaluate_pair(
                        obs_a, obs_b, conflict_id=f"CONF-{conflict_idx:03d}"
                    )
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
        """Evaluate if two observations form a reportable conflict."""
        a_is_healthy = obs_a.status == HealthStatus.HEALTHY
        b_is_healthy = obs_b.status == HealthStatus.HEALTHY
        a_is_unhealthy = obs_a.status in (HealthStatus.DEGRADED, HealthStatus.FAILED)
        b_is_unhealthy = obs_b.status in (HealthStatus.DEGRADED, HealthStatus.FAILED)

        # Check for opposing health statuses
        if not ((a_is_healthy and b_is_unhealthy) or (b_is_healthy and a_is_unhealthy)):
            return None

        # Check if differing scopes explain the apparent disagreement
        if obs_a.scope != obs_b.scope:
            return Conflict(
                id=conflict_id,
                conflict_type=ConflictType.SCOPE_TENSION,
                component=obs_a.component,
                evidence_ids=[obs_a.id, obs_b.id],
                headline=f"Scope Tension on {obs_a.component.value}: Workload vs Synthetic Probe",
                description=(
                    f"Source '{obs_a.source}' ({obs_a.scope}) reports {obs_a.status.value} ({obs_a.signal}={obs_a.value}{obs_a.unit}), "
                    f"while source '{obs_b.source}' ({obs_b.scope}) reports {obs_b.status.value} ({obs_b.signal}={obs_b.value}{obs_b.unit})."
                ),
                operational_implication=(
                    "Both observations are accurate within their measurement scopes: the component responds normally to direct synthetic probes, "
                    "but experiences degradation under actual production workload due to upstream or downstream dependencies."
                ),
            )

        # Check temporal overlap for same scope
        windows_overlap = (obs_a.window_start <= obs_b.window_end) and (
            obs_b.window_start <= obs_a.window_end
        )

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

        # Direct contradiction: same scope, overlapping window, opposing status
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

    def __init__(self, policy: PolicyEngine) -> None:
        self.policy = policy

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
                    is_capped=False,
                )

                if rel_str == "supports":
                    supporting_candidates.append(score_item)
                elif rel_str == "opposes":
                    opposing_candidates.append(score_item)

            # Apply per-source-group cap
            supporting_scored = self._apply_source_group_cap(supporting_candidates)
            opposing_scored = self._apply_source_group_cap(opposing_candidates)

            # Calculate net evidence
            support_total = sum(s.total_strength for s in supporting_scored if not s.is_capped)
            oppose_total = sum(s.total_strength for s in opposing_scored if not s.is_capped)
            net_score = max(0.0, float(support_total - oppose_total))

            raw_net_scores[code] = net_score

            draft = draft_map.get(code)
            summary_val = draft.summary if draft else cause_def["description"]
            causal_chain_val = draft.causal_chain if draft else [
                f"Trigger root cause: {cause_def['name']}",
                "Cascades through intermediate service layers",
                "Surfaces as operational latency and connection exhaustion"
            ]
            uncertainties_val = draft.unresolved_uncertainties if draft else [
                f"Remaining uncertainty regarding exact propagation dynamics of {cause_def['name']}."
            ]

            temp_evaluations.append({
                "cause_code": code,
                "name": cause_def["name"],
                "summary": summary_val,
                "causal_chain": causal_chain_val,
                "supporting_observations": supporting_scored,
                "opposing_observations": opposing_scored,
                "supporting_score": float(support_total),
                "opposing_score": float(oppose_total),
                "net_evidence_score": net_score,
                "unresolved_uncertainties": uncertainties_val,
            })

        # Calculate decision weights (normalized over positive net scores)
        total_positive_net = sum(raw_net_scores.values())

        for temp in temp_evaluations:
            code = temp["cause_code"]
            net = temp["net_evidence_score"]

            if total_positive_net > 0:
                decision_weight = round((net / total_positive_net) * 100.0, 1)
            else:
                decision_weight = 0.0

            # Determine strength band
            distinct_supporting_groups = {
                s.source_group for s in temp["supporting_observations"] if not s.is_capped
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
        """Compute freshness score anchored to incident timestamp."""
        diff_seconds = abs((incident_at - observed_at).total_seconds())
        if diff_seconds <= self.policy.freshness_thresholds["current_max"]:
            return self.policy.freshness_weights["current"]
        if diff_seconds <= self.policy.freshness_thresholds["recent_max"]:
            return self.policy.freshness_weights["recent"]
        return self.policy.freshness_weights["stale"]

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
        for group, items in by_group.items():
            # Sort descending by total_strength
            sorted_items = sorted(items, key=lambda x: x.total_strength, reverse=True)
            # Dominant item is uncapped
            for idx, item in enumerate(sorted_items):
                is_capped = idx > 0
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
                        is_capped=is_capped,
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
        """Rank strategies based on causal expected impact, safety, speed, and affordability."""
        weights = self.policy.scoring_weights
        w_impact = weights["impact"]
        w_safety = weights["safety"]
        w_speed = weights["speed"]
        w_affordability = weights["affordability"]

        # Map cause decision weights (0.0 - 1.0)
        cause_weights = {
            h.cause_code.value: (h.decision_weight / 100.0) for h in evaluated_hypotheses
        }

        scores: list[StrategyScore] = []

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

            score_entry = StrategyScore(
                strategy_id=strat_id,
                name=strat_def["name"],
                description=strat_def["description"],
                expected_impact=round(expected_impact, 2),
                safety=round(safety, 2),
                speed=round(speed, 2),
                affordability=round(affordability, 2),
                final_score=round(final_score, 2),
                rank=0, # Populated after sorting
                risk_notes=strat_def["risk_notes"],
                reversibility=strat_def["reversibility"],
            )
            scores.append(score_entry)

        # Deterministic sorting with tie-breaking:
        # 1. Higher final_score
        # 2. Higher expected_impact
        # 3. Higher safety
        # 4. Higher speed
        # 5. Lexicographically smaller strategy_id
        scores.sort(
            key=lambda s: (
                -s.final_score,
                -s.expected_impact,
                -s.safety,
                -s.speed,
                s.strategy_id,
            )
        )

        for rank_idx, item in enumerate(scores, start=1):
            item.rank = rank_idx

        return scores
