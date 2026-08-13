"""Investigation lifecycle orchestrator and state machine for Faultline."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from faultline.diagnostics import DiagnosticService, EvidenceLedger, ScenarioRepository
from faultline.gemini import GeminiProvider, LLMProviderProtocol
from faultline.models import (
    AnalysisResult,
    ExecutionSafetySection,
    FaultReport,
    HypothesisDraft,
    InvestigationTraceItem,
    LifecycleState,
    RootCauseCode,
)
from faultline.reasoning import (
    ConflictDetector,
    EvidenceEvaluator,
    PolicyEngine,
    StrategyRanker,
)
from faultline.validation import ReportValidator

logger = logging.getLogger(__name__)


class OrchestratorError(Exception):
    """Raised when an error occurs during investigation orchestration."""
    pass


class IncidentOrchestrator:
    """Controls the end-to-end incident investigation state machine, tool budgeting, and report assembly."""

    def __init__(
        self,
        provider: Optional[LLMProviderProtocol] = None,
        policy: Optional[PolicyEngine] = None,
        scenario_repo: Optional[ScenarioRepository] = None,
        max_rounds: int = 3,
        max_tool_attempts: int = 5,
    ) -> None:
        self.policy = policy or PolicyEngine()
        self.scenario_repo = scenario_repo or ScenarioRepository()
        self.provider = provider or GeminiProvider()
        self.max_rounds = max_rounds
        self.max_tool_attempts = max_tool_attempts
        self.validator = ReportValidator(self.policy)

    def analyze_scenario(self, scenario_id: str) -> AnalysisResult:
        """Run complete incident investigation for a given scenario ID."""
        run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
        trace: list[InvestigationTraceItem] = []

        def record_trace(
            round_idx: int,
            action_type: str,
            summary: str,
            tool_name: Optional[str] = None,
            details: Optional[dict[str, Any]] = None,
        ) -> None:
            trace.append(
                InvestigationTraceItem(
                    round_index=round_idx,
                    action_type=action_type,
                    timestamp=datetime.now(timezone.utc),
                    tool_name=tool_name,
                    summary=summary,
                    details=details or {},
                )
            )

        # -------------------------------------------------------------------
        # 1. State: RECEIVED
        # -------------------------------------------------------------------
        current_state = LifecycleState.RECEIVED
        scenario_data = self.scenario_repo.get_scenario(scenario_id)
        incident_at = DiagnosticService._parse_iso_timestamp(scenario_data["incident_at"])
        ledger = EvidenceLedger(incident_at=incident_at)
        diagnostic_service = DiagnosticService(scenario_data, ledger)

        raw_fault = scenario_data["initial_fault_report"]
        fault_report = FaultReport(
            source=raw_fault["source"],
            severity=raw_fault["severity"],
            headline=raw_fault["headline"],
            reported_at=incident_at,
            details=raw_fault["details"],
        )

        record_trace(
            0,
            "state_change",
            f"Incident alert received: {fault_report.headline} (Severity: {fault_report.severity})",
            details={"scenario_id": scenario_id, "run_id": run_id, "state": current_state.value},
        )

        # -------------------------------------------------------------------
        # 2. State: COLLECTING (Bounded Diagnostic Loop)
        # -------------------------------------------------------------------
        current_state = LifecycleState.COLLECTING
        available_tools = ["query_telemetry", "run_health_probes", "fetch_operational_events"]
        executed_tool_signatures: set[str] = set()
        total_tool_attempts = 0

        def execute_tool(t_name: str, args: dict[str, Any], round_num: int) -> dict[str, Any]:
            nonlocal total_tool_attempts
            total_tool_attempts += 1
            if t_name == "query_telemetry":
                res = diagnostic_service.query_telemetry(**args)
            elif t_name == "run_health_probes":
                res = diagnostic_service.run_health_probes(**args)
            elif t_name == "fetch_operational_events":
                res = diagnostic_service.fetch_operational_events(**args)
            else:
                res = {"error": f"Unknown tool: {t_name}"}

            record_trace(
                round_num,
                "tool_result",
                f"Executed '{t_name}': {res.get('summary', 'recorded observations to ledger')}",
                tool_name=t_name,
                details=res,
            )
            return res

        for round_idx in range(1, self.max_rounds + 1):
            remaining_attempts = self.max_tool_attempts - total_tool_attempts
            if remaining_attempts <= 0:
                record_trace(
                    round_idx,
                    "budget_limit",
                    "Maximum tool attempt budget reached.",
                )
                break

            # Ask provider for diagnostic action batch
            action_batch = self.provider.choose_diagnostics(
                incident=fault_report,
                evidence_ledger=ledger.get_observations(),
                round_index=round_idx,
                available_tools=available_tools,
                remaining_attempts=remaining_attempts,
            )

            record_trace(
                round_idx,
                "model_reasoning",
                f"Agent evaluated diagnostic state: requested {len(action_batch.tool_calls)} tool(s).",
                details={
                    "investigation_complete": action_batch.investigation_complete,
                    "tool_calls": [t.model_dump(mode="json") for t in action_batch.tool_calls],
                },
            )

            # Check if agent deemed collection complete (requires comprehensive coverage across all 3 source groups)
            if action_batch.investigation_complete and len(ledger.successful_source_groups) >= len(available_tools):
                record_trace(
                    round_idx,
                    "collection_complete",
                    "Agent concluded multi-source evidence collection is sufficient.",
                )
                break

            # Execute tool calls
            for tool_call in action_batch.tool_calls:
                if total_tool_attempts >= self.max_tool_attempts:
                    break

                tool_sig = f"{tool_call.tool_name}:{tool_call.component}:{tool_call.dimension}"
                if tool_sig in executed_tool_signatures:
                    total_tool_attempts += 1
                    record_trace(
                        round_idx,
                        "duplicate_suppression",
                        f"Suppressed duplicate tool call '{tool_call.tool_name}'.",
                        tool_name=tool_call.tool_name,
                    )
                    continue

                executed_tool_signatures.add(tool_sig)
                call_args = {}
                if tool_call.component:
                    call_args["component"] = tool_call.component
                if tool_call.dimension:
                    call_args["dimension"] = tool_call.dimension
                execute_tool(tool_call.tool_name, call_args, round_idx)

            # Ensure minimum source group coverage across all available diagnostic tools
            if round_idx == self.max_rounds and len(ledger.successful_source_groups) < len(available_tools):
                for fallback_tool in available_tools:
                    if total_tool_attempts >= self.max_tool_attempts:
                        break
                    if fallback_tool not in [t.split(":")[0] for t in executed_tool_signatures]:
                        executed_tool_signatures.add(f"{fallback_tool}:None:None")
                        execute_tool(fallback_tool, {}, round_idx)

        if len(ledger.successful_source_groups) < 2:
            raise OrchestratorError("Failed to collect evidence from at least 2 independent source groups within budget.")

        # -------------------------------------------------------------------
        # 3. State: RECONCILING (Conflict Classification)
        # -------------------------------------------------------------------
        current_state = LifecycleState.RECONCILING
        conflicts = ConflictDetector.detect_conflicts(ledger)
        record_trace(
            self.max_rounds + 1,
            "state_change",
            f"Classified {len(conflicts)} diagnostic conflict(s) / scope tension(s).",
            details={"conflicts": [c.model_dump(mode="json") for c in conflicts]},
        )

        # -------------------------------------------------------------------
        # 4. State: HYPOTHESIZING (Agentic Hypothesis Generation & Citation Verification)
        # -------------------------------------------------------------------
        current_state = LifecycleState.HYPOTHESIZING
        allowed_causes = list(RootCauseCode)
        hypothesis_draft_set = self.provider.synthesise_hypotheses(
            incident=fault_report,
            evidence_ledger=ledger.get_observations(),
            allowed_causes=allowed_causes,
        )

        # Validate Gemini draft citations immediately (C3)
        valid_evidence_ids = ledger.get_observation_ids()
        validated_drafts: list[HypothesisDraft] = []
        for draft in hypothesis_draft_set.hypotheses:
            invalid_citations = [
                eid for eid in (draft.supporting_evidence_ids + draft.opposing_evidence_ids)
                if eid not in valid_evidence_ids
            ]
            if invalid_citations:
                raise OrchestratorError(
                    f"Fabricated evidence citations {invalid_citations} detected in model hypothesis for {draft.cause_code.value}."
                )
            validated_drafts.append(draft)

        record_trace(
            self.max_rounds + 2,
            "state_change",
            f"Agent synthesized {len(validated_drafts)} verified root-cause candidate(s).",
            details={"hypotheses": [h.model_dump(mode="json") for h in validated_drafts]},
        )

        # -------------------------------------------------------------------
        # 5. State: SCORING (Deterministic Full-Catalogue Evidence Evaluation)
        # -------------------------------------------------------------------
        current_state = LifecycleState.SCORING
        evaluator = EvidenceEvaluator(self.policy)

        # Evaluate the full cause catalogue to ensure deterministic authority across all causes (C2)
        all_evaluated_hypotheses = evaluator.evaluate_hypotheses(
            candidate_codes=allowed_causes,
            ledger=ledger,
            draft_hypotheses=validated_drafts,
        )

        # Present hypotheses that have positive evidence or were shortlisted by the agent
        shortlisted_codes = {d.cause_code for d in validated_drafts}
        presented_hypotheses = [
            h for h in all_evaluated_hypotheses
            if h.cause_code in shortlisted_codes or h.net_evidence_score > 0
        ]
        if not presented_hypotheses:
            presented_hypotheses = all_evaluated_hypotheses[:4]

        record_trace(
            self.max_rounds + 3,
            "state_change",
            f"Evaluated evidence strength: Top candidate '{all_evaluated_hypotheses[0].name}' (Net Score: {all_evaluated_hypotheses[0].net_evidence_score}, Decision Weight: {all_evaluated_hypotheses[0].decision_weight}%).",
        )

        # -------------------------------------------------------------------
        # 6. State: REPORTING (4D Strategy Ranking & Trade-off Explanation)
        # -------------------------------------------------------------------
        current_state = LifecycleState.REPORTING
        ranker = StrategyRanker(self.policy)
        ranked_strategies = ranker.rank_strategies(all_evaluated_hypotheses)
        winning_strategy = ranked_strategies[0]

        # Identify top alternative for trade-off contrast (fastest distinct alternative)
        fastest_alternative = max(
            [s for s in ranked_strategies if s.strategy_id != winning_strategy.strategy_id],
            key=lambda s: s.speed,
        )

        explanation = self.provider.explain_decision(
            incident=fault_report,
            evidence_ledger=ledger.get_observations(),
            conflicts=conflicts,
            hypotheses=presented_hypotheses,
            strategy_ranking=ranked_strategies,
            winning_strategy=winning_strategy,
            top_alternative=fastest_alternative,
        )

        # Build strategy-specific execution guidance deterministically from winning strategy (H2)
        winning_strat_policy = self.policy.strategies.get(winning_strategy.strategy_id, {})
        execution_section = ExecutionSafetySection(
            execution_status="not_executed",
            operator_approval_required=True,
            suggested_command=winning_strat_policy.get("suggested_command", "echo 'No repair command defined'"),
            safety_preconditions=winning_strat_policy.get("preconditions", [
                "Verify system telemetry reaches stable baseline before operator confirmation."
            ]),
        )

        record_trace(
            self.max_rounds + 4,
            "state_change",
            f"Ranked {len(ranked_strategies)} repair strategies: Rank #1 is '{winning_strategy.name}'.",
        )

        # -------------------------------------------------------------------
        # 7. State: VALIDATING -> VALIDATED
        # -------------------------------------------------------------------
        current_state = LifecycleState.VALIDATING
        result = AnalysisResult(
            run_id=run_id,
            scenario_id=scenario_id,
            state=LifecycleState.VALIDATING,
            incident={
                "title": scenario_data["title"],
                "description": scenario_data["description"],
                "headline": fault_report.headline,
                "severity": fault_report.severity,
                "reported_at": fault_report.reported_at.isoformat(),
                "details": fault_report.details,
                "affected_components": scenario_data["affected_components"],
            },
            model_execution=self.provider.get_execution_metadata(),
            investigation_trace=trace,
            evidence=ledger.get_observations(),
            conflicts=conflicts,
            hypotheses=presented_hypotheses,
            strategy_ranking=ranked_strategies,
            recommendation=explanation,
            execution=execution_section,
            validation_passed=False,
        )

        # Strict validation
        self.validator.validate(result)
        result.validation_passed = True
        result.state = LifecycleState.VALIDATED

        val_event = InvestigationTraceItem(
            round_index=self.max_rounds + 5,
            action_type="validation",
            timestamp=datetime.now(timezone.utc),
            summary="Report passed all strict validation and safety checks.",
            details={"state": LifecycleState.VALIDATED.value, "validation_passed": True},
        )
        result.investigation_trace.append(val_event)

        return result
