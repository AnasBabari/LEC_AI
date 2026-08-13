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
            details={"scenario_id": scenario_id, "run_id": run_id},
        )

        # -------------------------------------------------------------------
        # 2. State: COLLECTING (Bounded Diagnostic Loop)
        # -------------------------------------------------------------------
        available_tools = ["query_telemetry", "run_health_probes", "fetch_operational_events"]
        executed_tool_signatures: set[str] = set()
        total_tool_attempts = 0

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

            # Check if agent deemed collection complete
            if action_batch.investigation_complete and len(ledger.successful_source_groups) >= 2:
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

                tool_sig = f"{tool_call.tool_name}:{sorted(tool_call.arguments.items())}"
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
                total_tool_attempts += 1

                # Execute adapter tool
                tool_res: dict[str, Any] = {}
                if tool_call.tool_name == "query_telemetry":
                    tool_res = diagnostic_service.query_telemetry(**tool_call.arguments)
                elif tool_call.tool_name == "run_health_probes":
                    tool_res = diagnostic_service.run_health_probes(**tool_call.arguments)
                elif tool_call.tool_name == "fetch_operational_events":
                    tool_res = diagnostic_service.fetch_operational_events(**tool_call.arguments)
                else:
                    tool_res = {"error": f"Unknown tool: {tool_call.tool_name}"}

                record_trace(
                    round_idx,
                    "tool_result",
                    f"Executed '{tool_call.tool_name}': {tool_res.get('summary', 'done')}",
                    tool_name=tool_call.tool_name,
                    details=tool_res,
                )

            # Ensure minimum source group coverage
            if round_idx == self.max_rounds and len(ledger.successful_source_groups) < 2:
                # Fallback: execute uncalled tools if budget permits
                for fallback_tool in available_tools:
                    if fallback_tool not in [t.split(":")[0] for t in executed_tool_signatures]:
                        if fallback_tool == "query_telemetry":
                            diagnostic_service.query_telemetry()
                        elif fallback_tool == "run_health_probes":
                            diagnostic_service.run_health_probes()
                        elif fallback_tool == "fetch_operational_events":
                            diagnostic_service.fetch_operational_events()

        if len(ledger.successful_source_groups) < 2:
            raise OrchestratorError("Failed to collect evidence from at least 2 independent source groups.")

        # -------------------------------------------------------------------
        # 3. State: RECONCILING (Conflict Classification)
        # -------------------------------------------------------------------
        conflicts = ConflictDetector.detect_conflicts(ledger)
        record_trace(
            self.max_rounds + 1,
            "state_change",
            f"Classified {len(conflicts)} diagnostic conflict(s) / scope tension(s).",
            details={"conflicts": [c.model_dump(mode="json") for c in conflicts]},
        )

        # -------------------------------------------------------------------
        # 4. State: HYPOTHESIZING (Agentic Hypothesis Generation)
        # -------------------------------------------------------------------
        allowed_causes = list(RootCauseCode)
        hypothesis_draft_set = self.provider.synthesise_hypotheses(
            incident=fault_report,
            evidence_ledger=ledger.get_observations(),
            allowed_causes=allowed_causes,
        )

        record_trace(
            self.max_rounds + 2,
            "state_change",
            f"Agent synthesized {len(hypothesis_draft_set.hypotheses)} root-cause candidate(s).",
            details={"hypotheses": [h.model_dump(mode="json") for h in hypothesis_draft_set.hypotheses]},
        )

        # -------------------------------------------------------------------
        # 5. State: SCORING (Deterministic Evidence Evaluation)
        # -------------------------------------------------------------------
        evaluator = EvidenceEvaluator(self.policy)
        candidate_codes = [h.cause_code for h in hypothesis_draft_set.hypotheses]
        evaluated_hypotheses = evaluator.evaluate_hypotheses(
            candidate_codes=candidate_codes,
            ledger=ledger,
            draft_hypotheses=hypothesis_draft_set.hypotheses,
        )

        record_trace(
            self.max_rounds + 3,
            "state_change",
            f"Evaluated evidence strength: Top candidate '{evaluated_hypotheses[0].name}' (Net Score: {evaluated_hypotheses[0].net_evidence_score}, Decision Weight: {evaluated_hypotheses[0].decision_weight}%).",
        )

        # -------------------------------------------------------------------
        # 6. State: REPORTING (4D Strategy Ranking & Trade-off Explanation)
        # -------------------------------------------------------------------
        ranker = StrategyRanker(self.policy)
        ranked_strategies = ranker.rank_strategies(evaluated_hypotheses)
        winning_strategy = ranked_strategies[0]

        # Identify top alternative for trade-off contrast (e.g. fastest or distinct second choice)
        fastest_alternative = max(
            [s for s in ranked_strategies if s.strategy_id != winning_strategy.strategy_id],
            key=lambda s: s.speed,
        )

        explanation = self.provider.explain_decision(
            incident=fault_report,
            evidence_ledger=ledger.get_observations(),
            conflicts=conflicts,
            hypotheses=evaluated_hypotheses,
            strategy_ranking=ranked_strategies,
            winning_strategy=winning_strategy,
            top_alternative=fastest_alternative,
        )

        execution_section = ExecutionSafetySection(
            execution_status="not_executed",
            operator_approval_required=True,
            suggested_command="kubectl rollout restart deployment/cache-invalidation-worker -n services && redis-cli info",
            safety_preconditions=[
                "Confirm message queue connection is healthy before worker restart.",
                "Verify database connection pool utilization stays below 95% during backlog replay.",
                "Monitor cache miss rate until hit ratio recovers above 90%.",
            ],
        )

        record_trace(
            self.max_rounds + 4,
            "state_change",
            f"Ranked {len(ranked_strategies)} repair strategies: Rank #1 is '{winning_strategy.name}'.",
        )

        # -------------------------------------------------------------------
        # 7. State: VALIDATING -> VALIDATED
        # -------------------------------------------------------------------
        result = AnalysisResult(
            run_id=run_id,
            scenario_id=scenario_id,
            state=LifecycleState.VALIDATED,
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
            hypotheses=evaluated_hypotheses,
            strategy_ranking=ranked_strategies,
            recommendation=explanation,
            execution=execution_section,
            validation_passed=False,
        )

        # Strict validation
        self.validator.validate(result)
        result.validation_passed = True

        record_trace(
            self.max_rounds + 5,
            "state_change",
            "Report passed all strict validation and safety checks.",
        )

        return result
