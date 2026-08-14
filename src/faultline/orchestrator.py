"""Investigation lifecycle orchestrator and state machine for Faultline."""

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from faultline.diagnostics import DiagnosticService, EvidenceLedger, ScenarioRepository
from faultline.gemini import GeminiProvider, LLMProviderProtocol
from faultline.models import (
    AdvantageDimension,
    AnalysisResult,
    AnalysisTimeoutError,
    ComponentEnum,
    DecisionExplanation,
    DiagnosticToolName,
    ExecutionSafetySection,
    FaultReport,
    HealthDimension,
    InsufficientEvidenceError,
    InvalidModelOutputError,
    InvestigationTraceItem,
    LifecycleState,
    ModelAuthenticationError,
    ModelRequestError,
    ModelUnavailableError,
    OrchestratorError,
    RootCauseCode,
    SourceGroup,
    StructuredDecisionGrounding,
)
from faultline.reasoning import (
    ConflictDetector,
    EvidenceEvaluator,
    PolicyEngine,
    StrategyRanker,
)
from faultline.validation import ReportValidator

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.RECEIVED: {LifecycleState.COLLECTING, LifecycleState.FAILED},
    LifecycleState.COLLECTING: {LifecycleState.RECONCILING, LifecycleState.FAILED},
    LifecycleState.RECONCILING: {LifecycleState.HYPOTHESIZING, LifecycleState.FAILED},
    LifecycleState.HYPOTHESIZING: {LifecycleState.SCORING, LifecycleState.FAILED},
    LifecycleState.SCORING: {LifecycleState.REPORTING, LifecycleState.FAILED},
    LifecycleState.REPORTING: {LifecycleState.VALIDATING, LifecycleState.FAILED},
    LifecycleState.VALIDATING: {LifecycleState.VALIDATED, LifecycleState.FAILED},
    LifecycleState.VALIDATED: set(),
    LifecycleState.FAILED: set(),
}

TOOL_TO_SOURCE_GROUP: dict[DiagnosticToolName, SourceGroup] = {
    DiagnosticToolName.QUERY_TELEMETRY: SourceGroup.TELEMETRY,
    DiagnosticToolName.RUN_HEALTH_PROBES: SourceGroup.HEALTH_PROBE,
    DiagnosticToolName.FETCH_OPERATIONAL_EVENTS: SourceGroup.OPERATIONAL_EVENTS,
}

SOURCE_GROUP_TO_TOOL: dict[SourceGroup, DiagnosticToolName] = {
    SourceGroup.TELEMETRY: DiagnosticToolName.QUERY_TELEMETRY,
    SourceGroup.HEALTH_PROBE: DiagnosticToolName.RUN_HEALTH_PROBES,
    SourceGroup.OPERATIONAL_EVENTS: DiagnosticToolName.FETCH_OPERATIONAL_EVENTS,
}


class IncidentOrchestrator:
    """Controls the end-to-end incident investigation state machine, tool budgeting, and report assembly."""

    def __init__(
        self,
        provider: Optional[LLMProviderProtocol] = None,
        policy: Optional[PolicyEngine] = None,
        scenario_repo: Optional[ScenarioRepository] = None,
        max_rounds: int = 3,
        max_tool_attempts: int = 8,
        analysis_deadline_seconds: float = 90.0,
    ) -> None:
        self.policy = policy or PolicyEngine()
        self.scenario_repo = scenario_repo or ScenarioRepository()
        self.provider = provider or GeminiProvider()
        self.max_rounds = max_rounds
        self.max_tool_attempts = max_tool_attempts
        self.analysis_deadline_seconds = analysis_deadline_seconds
        self.validator = ReportValidator(self.policy)

    def analyze_scenario(self, scenario_id: str) -> AnalysisResult:
        """Run complete incident investigation for a given scenario ID with strict state transitions and error handling."""
        start_monotonic = time.monotonic()
        run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
        trace: list[InvestigationTraceItem] = []
        current_state = LifecycleState.RECEIVED

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

        def transition_to(new_state: LifecycleState, summary: Optional[str] = None, details: Optional[dict[str, Any]] = None) -> None:
            nonlocal current_state
            if new_state not in ALLOWED_TRANSITIONS.get(current_state, set()):
                raise OrchestratorError(f"Illegal state transition from {current_state.value} to {new_state.value}")
            previous_state = current_state
            current_state = new_state
            record_trace(
                0,
                "state_change",
                summary or f"State transitioned: {previous_state.value} -> {new_state.value}",
                details={"from_state": previous_state.value, "to_state": new_state.value, **(details or {})},
            )

        def check_deadline() -> None:
            elapsed = time.monotonic() - start_monotonic
            if elapsed > self.analysis_deadline_seconds:
                raise AnalysisTimeoutError(
                    f"Analysis deadline of {self.analysis_deadline_seconds}s exceeded (elapsed: {elapsed:.1f}s)."
                )

        try:
            # 1. State: RECEIVED
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

            # 2. State: COLLECTING
            transition_to(LifecycleState.COLLECTING, "Beginning diagnostic collection loop.")
            session = self.provider.create_session()
            available_tool_names = [t.value for t in DiagnosticToolName]
            executed_tool_signatures: set[str] = set()
            total_tool_attempts = 0

            def execute_tool(t_name: str, args: dict[str, Any], round_num: int) -> dict[str, Any]:
                nonlocal total_tool_attempts
                total_tool_attempts += 1
                before_count = len(ledger.get_observations())
                if t_name == DiagnosticToolName.QUERY_TELEMETRY.value:
                    res = diagnostic_service.query_telemetry(**args)
                elif t_name == DiagnosticToolName.RUN_HEALTH_PROBES.value:
                    res = diagnostic_service.run_health_probes(**args)
                elif t_name == DiagnosticToolName.FETCH_OPERATIONAL_EVENTS.value:
                    res = diagnostic_service.fetch_operational_events(**args)
                else:
                    res = {"error": f"Unknown tool: {t_name}"}

                after_count = len(ledger.get_observations())
                appended = after_count - before_count
                records_returned = int(
                    len(res.get("records", []))
                    or res.get("observations_count")
                    or res.get("probes_executed")
                    or res.get("events_count")
                    or appended
                )
                deduplicated = max(0, records_returned - appended)

                summary_msg = f"Executed '{t_name}': {res.get('summary', 'recorded observations')} (Returned: {records_returned}, Appended: {appended}, Deduplicated: {deduplicated})"
                record_trace(
                    round_num,
                    "tool_result",
                    summary_msg,
                    tool_name=t_name,
                    details={
                        "records_returned": records_returned,
                        "records_appended": appended,
                        "records_deduplicated": deduplicated,
                        **res,
                    },
                )
                return res

            for round_idx in range(1, self.max_rounds + 1):
                check_deadline()
                remaining_attempts = self.max_tool_attempts - total_tool_attempts
                if total_tool_attempts >= self.max_tool_attempts:
                    record_trace(round_idx, "budget_limit", "Maximum tool attempt budget reached.")
                    break

                action_batch = self.provider.choose_diagnostics(
                    incident=fault_report,
                    evidence_ledger=ledger.get_observations(),
                    round_index=round_idx,
                    available_tools=available_tool_names,
                    remaining_attempts=remaining_attempts,
                    session=session,
                )

                for tool_call in action_batch.tool_calls:
                    if total_tool_attempts >= self.max_tool_attempts:
                        break
                    tool_name_str = tool_call.tool_name.value if isinstance(tool_call.tool_name, DiagnosticToolName) else str(tool_call.tool_name)
                    comp_str = tool_call.component.value if isinstance(tool_call.component, ComponentEnum) else str(tool_call.component)
                    dim_str = tool_call.dimension.value if isinstance(tool_call.dimension, HealthDimension) else str(tool_call.dimension)
                    tool_sig = f"{tool_name_str}:{comp_str}:{dim_str}"
                    if tool_sig in executed_tool_signatures:
                        continue
                    executed_tool_signatures.add(tool_sig)
                    execute_tool(tool_name_str, {"component": tool_call.component, "dimension": tool_call.dimension}, round_idx)

                if action_batch.investigation_complete and len(ledger.successful_source_groups) >= 3:
                    record_trace(round_idx, "collection_complete", "Agent concluded multi-source evidence collection is sufficient across all domains.")
                    break

            if len(ledger.successful_source_groups) < 3:
                missing_groups = {SourceGroup.TELEMETRY, SourceGroup.HEALTH_PROBE, SourceGroup.OPERATIONAL_EVENTS} - ledger.successful_source_groups
                for missing_group in missing_groups:
                    check_deadline()
                    if total_tool_attempts >= self.max_tool_attempts:
                        break
                    broad_tool = SOURCE_GROUP_TO_TOOL[missing_group]
                    execute_tool(broad_tool.value, {}, self.max_rounds)

            if len(ledger.successful_source_groups) < 2:
                raise InsufficientEvidenceError("Failed to collect evidence from at least 2 independent source groups.")

            # 3. State: RECONCILING
            transition_to(LifecycleState.RECONCILING, "Reconciling evidence and classifying diagnostic conflicts.")
            check_deadline()
            conflicts = ConflictDetector.detect_conflicts(ledger)
            record_trace(self.max_rounds + 1, "reconciliation", f"Classified {len(conflicts)} diagnostic conflict(s).")

            # 4. State: HYPOTHESIZING
            transition_to(LifecycleState.HYPOTHESIZING, "Synthesizing and validating candidate root-cause hypotheses.")
            check_deadline()
            allowed_causes = list(RootCauseCode)
            hypothesis_draft_set = self.provider.synthesise_hypotheses(incident=fault_report, evidence_ledger=ledger.get_observations(), allowed_causes=allowed_causes, session=session)
            evaluator = EvidenceEvaluator(self.policy)
            validated_drafts = []
            for draft in hypothesis_draft_set.hypotheses:
                if draft.supporting_evidence_ids:
                    is_valid, _ = evaluator.validate_hypothesis_citations(draft, ledger.get_observations())
                    if is_valid:
                        validated_drafts.append(draft)

            if len(validated_drafts) < 2:
                validation_errors = []
                for d in hypothesis_draft_set.hypotheses:
                    _, errs = evaluator.validate_hypothesis_citations(d, ledger.get_observations())
                    if errs:
                        validation_errors.extend(errs)
                try:
                    repaired_set = self.provider.repair_hypotheses(incident=fault_report, evidence_ledger=ledger.get_observations(), allowed_causes=allowed_causes, previous_drafts=hypothesis_draft_set.hypotheses, validation_errors=validation_errors, session=session)
                    validated_drafts = [d for d in repaired_set.hypotheses if d.supporting_evidence_ids and evaluator.validate_hypothesis_citations(d, ledger.get_observations())[0]]
                except (ModelUnavailableError, AnalysisTimeoutError, ModelAuthenticationError, ModelRequestError):
                    raise
                except (InvalidModelOutputError, ValueError) as rep_err:
                    logger.warning(f"Semantic hypothesis repair failed: {rep_err}")
                if len(validated_drafts) < 2:
                    raise InvalidModelOutputError("Model failed to provide at least 2 valid grounded root-cause hypotheses.")

            # 5. State: SCORING
            transition_to(LifecycleState.SCORING, "Deterministically evaluating full cause catalogue.")
            check_deadline()
            all_evaluated_hypotheses = evaluator.evaluate_hypotheses(candidate_codes=allowed_causes, ledger=ledger, draft_hypotheses=validated_drafts)
            top_cause = all_evaluated_hypotheses[0] if all_evaluated_hypotheses else None
            record_trace(self.max_rounds + 3, "deterministic_scoring", f"Leading root cause is '{top_cause.name if top_cause else 'Unknown'}'", details={"evaluated_hypotheses": [{"cause_code": h.cause_code.value, "net_score": h.net_evidence_score, "band": h.strength_band.value} for h in all_evaluated_hypotheses]})

            # 6. State: REPORTING
            transition_to(LifecycleState.REPORTING, "Synthesizing repair strategy trade-offs and decision narrative.")
            check_deadline()
            ranker = StrategyRanker(self.policy)
            ranked_strategies = ranker.rank_strategies(all_evaluated_hypotheses)
            winning_strategy = ranked_strategies[0]
            non_winning = [s for s in ranked_strategies if s.strategy_id != winning_strategy.strategy_id]
            fastest_alternative = max(non_winning, key=lambda s: s.speed) if non_winning else winning_strategy

            shortlisted_codes = {d.cause_code for d in validated_drafts}
            presented_hypotheses = [
                h for h in all_evaluated_hypotheses if h.cause_code in shortlisted_codes or h.net_evidence_score > 0
            ]
            if not presented_hypotheses:
                presented_hypotheses = all_evaluated_hypotheses[:4]

            narrative_draft = self.provider.explain_decision(incident=fault_report, evidence_ledger=ledger.get_observations(), conflicts=conflicts, hypotheses=presented_hypotheses, strategy_ranking=ranked_strategies, winning_strategy=winning_strategy, top_alternative=fastest_alternative, session=session)

            win_val, alt_val, alt_dim = 0.0, 0.0, AdvantageDimension.NONE
            if fastest_alternative.speed > winning_strategy.speed:
                alt_dim, alt_val, win_val = AdvantageDimension.SPEED, fastest_alternative.speed, winning_strategy.speed
            elif fastest_alternative.affordability > winning_strategy.affordability:
                alt_dim, alt_val, win_val = AdvantageDimension.AFFORDABILITY, fastest_alternative.affordability, winning_strategy.affordability
            elif fastest_alternative.safety > winning_strategy.safety:
                alt_dim, alt_val, win_val = AdvantageDimension.SAFETY, fastest_alternative.safety, winning_strategy.safety

            grounding = StructuredDecisionGrounding(
                winning_strategy_id=winning_strategy.strategy_id,
                winning_strategy_name=winning_strategy.name,
                top_cause_code=top_cause.cause_code if top_cause else RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
                reconciled_conflict_ids=[c.id for c in conflicts],
                reconciled_evidence_ids=[eid for c in conflicts for eid in c.evidence_ids],
                referenced_conflict_ids=list(narrative_draft.referenced_conflict_ids),
                referenced_evidence_ids=list(narrative_draft.referenced_evidence_ids),
                alternative_strategy_id=fastest_alternative.strategy_id,
                alternative_strategy_name=fastest_alternative.name,
                alternative_advantage_dimension=alt_dim,
                alternative_advantage_value=alt_val,
                winning_advantage_value=win_val,
                rejection_risk_factor=fastest_alternative.risk_notes or "Operational risk",
            )

            explanation = DecisionExplanation(
                executive_summary=narrative_draft.executive_summary,
                winning_strategy_id=winning_strategy.strategy_id,
                trade_off_comparison=narrative_draft.trade_off_comparison,
                grounded_contradiction_analysis=narrative_draft.grounded_contradiction_analysis,
                remaining_uncertainties=narrative_draft.remaining_uncertainties,
                grounding=grounding,
            )

            winning_strat_policy = self.policy.strategies.get(winning_strategy.strategy_id, {})
            execution_section = ExecutionSafetySection(
                execution_status="not_executed",
                operator_approval_required=True,
                suggested_command=winning_strat_policy.get("suggested_command", "echo 'No repair command defined'"),
                safety_preconditions=winning_strat_policy.get(
                    "preconditions", ["Verify system telemetry reaches stable baseline before operator confirmation."]
                ),
            )

            record_trace(
                self.max_rounds + 4,
                "strategy_ranking",
                f"Ranked {len(ranked_strategies)} repair strategies: Rank #1 is '{winning_strategy.name}'.",
            )

            # ---------------------------------------------------------------
            # 7. State: VALIDATING -> VALIDATED
            # ---------------------------------------------------------------
            transition_to(LifecycleState.VALIDATING, "Validating complete report against safety and provenance invariants.")
            check_deadline()

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
                model_execution=self.provider.get_execution_metadata(session=session),
                investigation_trace=trace,
                evidence=ledger.get_observations(),
                conflicts=conflicts,
                hypotheses=presented_hypotheses,
                strategy_ranking=ranked_strategies,
                recommendation=explanation,
                execution=execution_section,
                validation_passed=False,
            )

            self.validator.validate(result)
            result.validation_passed = True
            transition_to(LifecycleState.VALIDATED, "Report passed all strict validation and safety checks.")
            result.state = current_state
            result.investigation_trace = list(trace)

            val_event = InvestigationTraceItem(
                round_index=self.max_rounds + 5,
                action_type="validation",
                timestamp=datetime.now(timezone.utc),
                summary="Report passed all strict validation and safety checks.",
                details={"state": LifecycleState.VALIDATED.value, "validation_passed": True},
            )
            result.investigation_trace.append(val_event)
            return result

        except Exception as e:
            logger.error(f"Investigation failed at state {current_state.value}: {e}")
            if current_state != LifecycleState.FAILED and current_state != LifecycleState.VALIDATED:
                try:
                    transition_to(LifecycleState.FAILED, f"Investigation failed: {type(e).__name__}: {e}")
                except Exception:
                    pass
            raise
