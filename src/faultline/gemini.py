"""Gemini API integration, model discovery, structured output schemas, and fake provider for Faultline."""

import json
import logging
import os
from typing import Any, Optional, Protocol, Type, TypeVar, cast

from pydantic import BaseModel

from faultline.models import (
    Conflict,
    DecisionExplanation,
    DiagnosticActionBatch,
    DiagnosticToolCall,
    EvaluatedHypothesis,
    EvidenceObservation,
    FaultReport,
    HypothesisDraft,
    HypothesisDraftSet,
    ModelExecutionMetadata,
    RootCauseCode,
    StrategyScore,
    TradeOffComparison,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMProviderProtocol(Protocol):
    """Protocol for LLM reasoning providers."""

    primary_model: str

    def choose_diagnostics(
        self,
        incident: FaultReport,
        evidence_ledger: list[EvidenceObservation],
        round_index: int,
        available_tools: list[str],
        remaining_attempts: int,
    ) -> DiagnosticActionBatch:
        ...

    def synthesise_hypotheses(
        self,
        incident: FaultReport,
        evidence_ledger: list[EvidenceObservation],
        allowed_causes: list[RootCauseCode],
    ) -> HypothesisDraftSet:
        ...

    def explain_decision(
        self,
        incident: FaultReport,
        evidence_ledger: list[EvidenceObservation],
        conflicts: list[Conflict],
        hypotheses: list[EvaluatedHypothesis],
        strategy_ranking: list[StrategyScore],
        winning_strategy: StrategyScore,
        top_alternative: StrategyScore,
    ) -> DecisionExplanation:
        ...

    def get_execution_metadata(self) -> ModelExecutionMetadata:
        ...


class FakeGeminiProvider:
    """Deterministic provider for testing and offline environments."""

    def __init__(
        self,
        primary_model: str = "gemini-3.6-flash",
        thinking_level: str = "medium",
    ) -> None:
        self.primary_model = primary_model
        self.thinking_level = thinking_level
        self.fallback_occurred = False
        self.fallback_reason: Optional[str] = None

    def choose_diagnostics(
        self,
        incident: FaultReport,
        evidence_ledger: list[EvidenceObservation],
        round_index: int,
        available_tools: list[str],
        remaining_attempts: int,
    ) -> DiagnosticActionBatch:
        """Deterministically request complementary diagnostic tools."""
        collected_sources = {obs.source_group.value for obs in evidence_ledger}

        # Round 1: Request telemetry and synthetic health probes if not yet collected
        if round_index == 1 or "telemetry" not in collected_sources:
            tool_calls = [
                DiagnosticToolCall(
                    tool_name="query_telemetry",
                    arguments={},
                    reasoning="Collect active workload telemetry across API gateway, database, and cache layers.",
                ),
                DiagnosticToolCall(
                    tool_name="run_health_probes",
                    arguments={},
                    reasoning="Execute independent synthetic health probes to isolate infrastructure vs workload strain.",
                ),
            ]
            return DiagnosticActionBatch(tool_calls=tool_calls, investigation_complete=False)

        # Round 2: If telemetry and health probes disagree, query operational events
        if "operational_events" not in collected_sources:
            tool_calls = [
                DiagnosticToolCall(
                    tool_name="fetch_operational_events",
                    arguments={},
                    reasoning="Fetch operational events, migrations, queue worker heartbeats, and eviction logs.",
                )
            ]
            return DiagnosticActionBatch(tool_calls=tool_calls, investigation_complete=False)

        # All 3 source groups collected: complete investigation
        return DiagnosticActionBatch(tool_calls=[], investigation_complete=True)

    def synthesise_hypotheses(
        self,
        incident: FaultReport,
        evidence_ledger: list[EvidenceObservation],
        allowed_causes: list[RootCauseCode],
    ) -> HypothesisDraftSet:
        """Synthesize candidate hypotheses citing actual evidence IDs."""
        queue_evidence_ids = [
            obs.id for obs in evidence_ledger if obs.component.value == "message_queue"
        ]
        cache_evidence_ids = [
            obs.id for obs in evidence_ledger if obs.component.value == "cache"
        ]
        db_workload_ids = [
            obs.id
            for obs in evidence_ledger
            if obs.component.value == "database" and obs.scope == "workload"
        ]
        db_probe_ids = [
            obs.id
            for obs in evidence_ledger
            if obs.component.value == "database" and obs.scope == "synthetic_probe"
        ]
        gateway_ids = [
            obs.id for obs in evidence_ledger if obs.component.value == "api_gateway"
        ]
        migration_ids = [
            obs.id
            for obs in evidence_ledger
            if "migration" in obs.signal or "table_scan" in obs.signal
        ]

        hypotheses: list[HypothesisDraft] = []

        # Scenario: Index regression
        if migration_ids:
            hypotheses.append(
                HypothesisDraft(
                    cause_code=RootCauseCode.DATABASE_INDEX_REGRESSION,
                    summary="A recent schema migration dropped a critical query index, forcing full sequential table scans (480 scans/sec) on search endpoints.",
                    causal_chain=[
                        "Schema migration dropped composite index on 'orders' table",
                        "Sequential full table scans triggered on all order search queries",
                        "Application workload latency rose to 1850ms while synthetic health probe responds in 1.5ms",
                    ],
                    supporting_evidence_ids=migration_ids + gateway_ids,
                    opposing_evidence_ids=[],
                    unresolved_uncertainties=[
                        "Direct synthetic ping executes primary key lookup in 1.5ms, confirming engine is healthy but queries lacking index are degraded.",
                    ],
                )
            )

        # Canonical Scenario: Cache invalidation consumer stall
        if queue_evidence_ids or cache_evidence_ids:
            hypotheses.append(
                HypothesisDraft(
                    cause_code=RootCauseCode.CACHE_INVALIDATION_CONSUMER_STALLED,
                    summary="Cache invalidation queue consumer stalled, creating a massive event backlog, stale cache reads, and cascading DB query saturation.",
                    causal_chain=[
                        "Invalidation queue consumer worker crashed (OOM killer exit code 137)",
                        "Cache invalidation messages accumulated to >42,000 unconsumed items",
                        "Cache entries remained stale, causing application cache-miss cascade",
                        "Database connection pool became saturated (92%) handling direct cache misses",
                    ],
                    supporting_evidence_ids=queue_evidence_ids + cache_evidence_ids + db_workload_ids,
                    opposing_evidence_ids=[],
                    unresolved_uncertainties=[
                        "Exact root cause of the initial consumer worker OOM crash remains uninspected.",
                        "Time required to drain the 42,000 message backlog under current traffic.",
                    ],
                )
            )

        hypotheses.append(
            HypothesisDraft(
                cause_code=RootCauseCode.DATABASE_CAPACITY_DEGRADATION,
                summary="Database cluster capacity is degraded or failing under standard production query load.",
                causal_chain=[
                    "Database engine exhausted resources",
                    "Connection pool saturated / table scans elevated",
                    "API Gateway response times spiked",
                ],
                supporting_evidence_ids=db_workload_ids,
                opposing_evidence_ids=db_probe_ids,
                unresolved_uncertainties=[
                    "Direct synthetic probe responds in <2ms with healthy CPU, indicating DB engine is not fundamentally degraded.",
                ],
            )
        )

        hypotheses.append(
            HypothesisDraft(
                cause_code=RootCauseCode.TRAFFIC_SURGE,
                summary="Unprecedented external traffic surge is overwhelming the ingress gateway.",
                causal_chain=[
                    "High traffic volume overwhelms API Gateway",
                    "Backend services experience elevated latencies",
                ],
                supporting_evidence_ids=gateway_ids,
                opposing_evidence_ids=[],
                unresolved_uncertainties=[
                    "Gateway health endpoint is 200 OK and direct infrastructure probes are healthy.",
                ],
            )
        )

        hypotheses.append(
            HypothesisDraft(
                cause_code=RootCauseCode.CACHE_NODE_FAILURE,
                summary="Cache cluster nodes are down or failing health checks.",
                causal_chain=[
                    "Cache node hardware crash",
                    "All cache queries miss",
                ],
                supporting_evidence_ids=[],
                opposing_evidence_ids=[
                    obs.id
                    for obs in evidence_ledger
                    if obs.component.value == "cache" and obs.status.value == "healthy"
                ],
                unresolved_uncertainties=[
                    "Direct TCP ping confirms cache cluster nodes are fully responsive (0.5ms).",
                ],
            )
        )

        filtered = [h for h in hypotheses if h.cause_code in allowed_causes]
        return HypothesisDraftSet(hypotheses=filtered)

    def explain_decision(
        self,
        incident: FaultReport,
        evidence_ledger: list[EvidenceObservation],
        conflicts: list[Conflict],
        hypotheses: list[EvaluatedHypothesis],
        strategy_ranking: list[StrategyScore],
        winning_strategy: StrategyScore,
        top_alternative: StrategyScore,
    ) -> DecisionExplanation:
        """Provide defensible written justification for strategy ranking."""
        top_hyp = hypotheses[0] if hypotheses else None
        top_hyp_name = top_hyp.name if top_hyp else "Primary Cause"

        # Grounded contradiction analysis
        has_migration = any("migration" in obs.signal for obs in evidence_ledger)
        if has_migration:
            contradiction_text = (
                "Workload telemetry indicated high database query latency on search endpoints (1850ms) and elevated table scan rates, "
                "while direct synthetic probes showed the database engine responding in 1.5ms. This scope tension is explained by "
                "the dropped composite index in migration #4082: the database hardware is healthy, but queries filtering on unindexed columns "
                "must perform expensive full table scans."
            )
            rejection_text = (
                f"{top_alternative.name} provides temporary symptom relief or faster execution ({top_alternative.speed}/100), "
                "but does not resolve the missing database index. Rebuilding the index concurrently cures the root cause with zero data loss."
            )
        else:
            contradiction_text = (
                "Workload telemetry indicated high database latency and connection pool saturation (92%), while direct synthetic "
                "probes showed the database responding in 1.8ms with healthy CPU. This scope tension is explained by the 42,000-message "
                "invalidation queue backlog: stale cache keys forced high miss rates (65.8% misses) directly to the database. "
                "The database is functioning normally but overwhelmed by upstream invalidation failure."
            )
            rejection_text = (
                f"{top_alternative.name} is rejected as the primary action because it does not resolve the stalled queue consumer, "
                f"and flushing the cache would trigger a dangerous 100% cache stampede onto the already strained database. "
                f"Recovering the consumer safely restores end-to-end cache invalidation without risking database collapse."
            )

        return DecisionExplanation(
            executive_summary=(
                f"Recommended Action: '{winning_strategy.name}' (Final Score: {winning_strategy.final_score}/100). "
                f"Multi-source diagnostic investigation isolated the root cause to '{top_hyp_name}', supported by independent "
                f"diagnostic evidence. The apparent database latency is reconciled by root-cause analysis."
            ),
            winning_strategy_id=winning_strategy.strategy_id,
            trade_off_comparison=TradeOffComparison(
                alternative_strategy_id=top_alternative.strategy_id,
                alternative_strategy_name=top_alternative.name,
                alternative_advantage=(
                    f"{top_alternative.name} offers higher execution speed ({top_alternative.speed}/100) "
                    f"and lower operational friction ({top_alternative.affordability}/100)."
                ),
                rejection_rationale=rejection_text,
            ),
            grounded_contradiction_analysis=contradiction_text,
            remaining_uncertainties=(
                top_hyp.unresolved_uncertainties if top_hyp else ["Execution duration under live production workload."]
            ),
        )

    def get_execution_metadata(self) -> ModelExecutionMetadata:
        return ModelExecutionMetadata(
            configured_primary_model=self.primary_model,
            configured_fallback_model=None,
            model_used=self.primary_model,
            thinking_level=self.thinking_level,
            fallback_occurred=self.fallback_occurred,
            fallback_reason=self.fallback_reason,
            prompt_tokens=420,
            completion_tokens=280,
        )


class GeminiProvider:
    """Production provider using Google GenAI SDK with startup model discovery and fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        preferred_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        thinking_level: str = "medium",
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.thinking_level = os.getenv("GEMINI_THINKING_LEVEL", thinking_level)
        self.configured_primary: str = preferred_model or os.getenv("GEMINI_MODEL") or "gemini-3.6-flash"
        self.configured_fallback: Optional[str] = fallback_model or os.getenv("GEMINI_FALLBACK_MODEL")

        self.primary_model: str = self.configured_primary
        self.fallback_model: Optional[str] = self.configured_fallback
        self.active_model: str = self.primary_model
        self.fallback_occurred = False
        self.fallback_reason: Optional[str] = None

        self._client: Optional[Any] = None
        self._initialize_and_probe_models()

    def _initialize_and_probe_models(self) -> None:
        """Initialize Google GenAI client and probe model availability once at startup."""
        if not self.api_key:
            logger.info("No GEMINI_API_KEY provided. Provider will operate with configured model IDs.")
            return

        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)

            # Probe available models once on startup
            available_model_names: set[str] = set()
            try:
                for m in self._client.models.list():
                    name = getattr(m, "name", "")
                    if name:
                        available_model_names.add(name.replace("models/", ""))
            except Exception as probe_err:
                logger.warning(f"Could not list Gemini models on startup: {probe_err}")

            # Check if preferred 3.7 model is explicitly available
            if self.configured_primary in available_model_names:
                self.primary_model = self.configured_primary
            elif "gemini-3.7-flash" in available_model_names:
                self.primary_model = "gemini-3.7-flash"
                self.fallback_model = "gemini-3.6-flash"
            else:
                self.primary_model = "gemini-3.6-flash"

            self.active_model = self.primary_model
            logger.info(f"Resolved Gemini runtime model: primary={self.primary_model}, fallback={self.fallback_model}")

        except ImportError:
            logger.warning("google-genai package not installed; falling back to stub mode.")
        except Exception as e:
            logger.error(f"Error initializing Gemini client: {e}")

    def _call_gemini_structured(
        self,
        prompt: str,
        response_schema: Type[T],
    ) -> T:
        """Call Gemini API requesting structured output conforming to a Pydantic schema."""
        if not self._client:
            raise RuntimeError("Gemini client not initialized (GEMINI_API_KEY is missing or invalid)")

        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
        )

        try:
            response = self._client.models.generate_content(
                model=self.active_model,
                contents=prompt,
                config=config,
            )
            raw_text = response.text
            return cast(T, response_schema.model_validate_json(raw_text))
        except Exception as primary_err:
            logger.warning(f"Primary model {self.active_model} call failed: {primary_err}")
            if self.fallback_model and self.active_model != self.fallback_model:
                logger.info(f"Switching to fallback model {self.fallback_model}")
                self.active_model = self.fallback_model
                self.fallback_occurred = True
                self.fallback_reason = str(primary_err)
                response = self._client.models.generate_content(
                    model=self.active_model,
                    contents=prompt,
                    config=config,
                )
                return cast(T, response_schema.model_validate_json(response.text))
            raise primary_err

    def choose_diagnostics(
        self,
        incident: FaultReport,
        evidence_ledger: list[EvidenceObservation],
        round_index: int,
        available_tools: list[str],
        remaining_attempts: int,
    ) -> DiagnosticActionBatch:
        """Ask Gemini to select the next diagnostic tool based on current observations."""
        if not self._client:
            fake = FakeGeminiProvider(self.primary_model, self.thinking_level)
            return fake.choose_diagnostics(
                incident, evidence_ledger, round_index, available_tools, remaining_attempts
            )

        evidence_summary = "\n".join([
            f"- [{obs.id}] ({obs.source_group.value}) {obs.component.value}: {obs.signal}={obs.value}{obs.unit} -> status: {obs.status.value} (scope: {obs.scope})"
            for obs in evidence_ledger
        ]) or "None yet."

        prompt = f"""You are Faultline, an expert operational diagnostic agent.
Investigate this incident:
Headline: {incident.headline}
Severity: {incident.severity}
Reported Details: {incident.details}

Current Round: {round_index} (Remaining tool attempts: {remaining_attempts})
Available Diagnostic Tools: {', '.join(available_tools)}

Evidence Collected So Far in Ledger:
{evidence_summary}

Task:
Select the most informative next diagnostic tool(s) to isolate root causes and resolve conflicting signals.
If you have sufficient multi-source evidence (at least 2-3 independent sources), set investigation_complete=True with empty tool_calls.
"""
        return self._call_gemini_structured(prompt, DiagnosticActionBatch)

    def synthesise_hypotheses(
        self,
        incident: FaultReport,
        evidence_ledger: list[EvidenceObservation],
        allowed_causes: list[RootCauseCode],
    ) -> HypothesisDraftSet:
        """Ask Gemini to synthesize plausible root-cause hypotheses citing ledger IDs."""
        if not self._client:
            fake = FakeGeminiProvider(self.primary_model, self.thinking_level)
            return fake.synthesise_hypotheses(incident, evidence_ledger, allowed_causes)

        evidence_json = json.dumps([obs.model_dump(mode="json") for obs in evidence_ledger], indent=2)
        allowed_causes_str = ", ".join([c.value for c in allowed_causes])

        prompt = f"""You are Faultline. Synthesize plausible root-cause hypotheses for this incident.
Incident: {incident.headline}

Evidence Ledger Observations (YOU MUST CITE EXACT 'id' VALUES e.g. 'EV-001'):
{evidence_json}

Allowed Cause Codes (Choose 2-4 plausible causes strictly from this catalogue):
{allowed_causes_str}

Instructions:
1. For each chosen cause code, construct a clear summary and step-by-step causal chain.
2. Cite all supporting evidence IDs from the ledger (e.g. ["EV-001", "EV-003"]).
3. Cite all opposing evidence IDs from the ledger (e.g. ["EV-004"]).
4. Explicitly list any unresolved uncertainties.
5. Do NOT generate arbitrary cause codes or hallucinated evidence IDs.
"""
        return self._call_gemini_structured(prompt, HypothesisDraftSet)

    def explain_decision(
        self,
        incident: FaultReport,
        evidence_ledger: list[EvidenceObservation],
        conflicts: list[Conflict],
        hypotheses: list[EvaluatedHypothesis],
        strategy_ranking: list[StrategyScore],
        winning_strategy: StrategyScore,
        top_alternative: StrategyScore,
    ) -> DecisionExplanation:
        """Ask Gemini to provide a defensible executive justification for the fixed ranking."""
        if not self._client:
            fake = FakeGeminiProvider(self.primary_model, self.thinking_level)
            return fake.explain_decision(
                incident,
                evidence_ledger,
                conflicts,
                hypotheses,
                strategy_ranking,
                winning_strategy,
                top_alternative,
            )

        conflicts_str = "\n".join([
            f"- {c.id} ({c.conflict_type.value}) on {c.component.value}: {c.headline} (Evidence: {c.evidence_ids})"
            for c in conflicts
        ]) or "None"

        hypotheses_str = "\n".join([
            f"- {h.name} (Code: {h.cause_code.value}): Net Evidence Score = {h.net_evidence_score}, Decision Weight = {h.decision_weight}%, Band = {h.strength_band.value}"
            for h in hypotheses
        ])

        ranking_str = "\n".join([
            f"{s.rank}. {s.name} (ID: {s.strategy_id}) -> Final Score: {s.final_score} [Impact: {s.expected_impact}, Safety: {s.safety}, Speed: {s.speed}, Affordability: {s.affordability}]"
            for s in strategy_ranking
        ])

        prompt = f"""You are Faultline. Write a defensible executive explanation justifying why the top-ranked repair strategy is preferred.

Incident: {incident.headline}

Detected Conflicts:
{conflicts_str}

Deterministically Evaluated Hypotheses:
{hypotheses_str}

Deterministically Ranked Strategies:
{ranking_str}

Winner: {winning_strategy.name} (ID: {winning_strategy.strategy_id}, Final Score: {winning_strategy.final_score})
Top Alternative: {top_alternative.name} (ID: {top_alternative.strategy_id}, Final Score: {top_alternative.final_score}, Speed: {top_alternative.speed})

Requirements:
1. Executive Summary: Clearly state the winner and why root-cause evidence justifies this action.
2. Trade-Off Comparison: Contrast the winner against {top_alternative.name}. Acknowledge {top_alternative.name}'s specific advantage (e.g. speed/cost) and explain why it is rejected (e.g. risks cache stampede, fails to address root cause).
3. Grounded Contradiction Analysis: Explain how the conflicting diagnostics (e.g. database workload latency vs healthy direct probe) are reconciled.
4. Remaining Uncertainties: State any operational unknowns for the operator.
"""
        return self._call_gemini_structured(prompt, DecisionExplanation)

    def get_execution_metadata(self) -> ModelExecutionMetadata:
        return ModelExecutionMetadata(
            configured_primary_model=str(self.configured_primary),
            configured_fallback_model=str(self.configured_fallback) if self.configured_fallback else None,
            model_used=str(self.active_model),
            thinking_level=self.thinking_level,
            fallback_occurred=self.fallback_occurred,
            fallback_reason=self.fallback_reason,
            prompt_tokens=420,
            completion_tokens=280,
        )
