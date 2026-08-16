"""Domain and API Pydantic models for Faultline."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceGroup(str, Enum):
    """Independent diagnostic measurement source groups."""

    TELEMETRY = "telemetry"
    HEALTH_PROBE = "health_probe"
    OPERATIONAL_EVENTS = "operational_events"


class ComponentEnum(str, Enum):
    """Monitored operational service components."""

    API_GATEWAY = "api_gateway"
    DATABASE = "database"
    CACHE = "cache"
    MESSAGE_QUEUE = "message_queue"


class HealthDimension(str, Enum):
    """Measured operational health dimensions."""

    LATENCY = "latency"
    AVAILABILITY = "availability"
    FRESHNESS = "freshness"
    THROUGHPUT = "throughput"
    BACKLOG = "backlog"
    QUERY_EFFICIENCY = "query_efficiency"


class HealthStatus(str, Enum):
    """Normalized status of an observation."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    INFORMATIONAL = "informational"
    UNKNOWN = "unknown"


class ReliabilityLevel(str, Enum):
    """Source reliability rating."""

    VERIFIED = "verified"  # Direct synthetic probe or kernel/runtime event (Weight: 3)
    AGGREGATED = "aggregated"  # Time-series metric aggregate / histogram (Weight: 2)
    ADVISORY = "advisory"  # Uncorrelated log or heuristic notice (Weight: 1)


class ConflictType(str, Enum):
    """Classification of diagnostic disagreement."""

    DIRECT_CONTRADICTION = "DIRECT_CONTRADICTION"  # Same component, compatible dimension, window, opposing status
    SCOPE_TENSION = "SCOPE_TENSION"  # Same component, different scopes (e.g. synthetic probe vs workload)
    TEMPORAL_CONFLICT = "TEMPORAL_CONFLICT"  # Disagreement explained by non-overlapping time windows


class RootCauseCode(str, Enum):
    """Closed catalogue of supported root-cause candidate codes."""

    CACHE_INVALIDATION_CONSUMER_STALLED = "CACHE_INVALIDATION_CONSUMER_STALLED"
    DATABASE_CAPACITY_DEGRADATION = "DATABASE_CAPACITY_DEGRADATION"
    CACHE_NODE_FAILURE = "CACHE_NODE_FAILURE"
    TRAFFIC_SURGE = "TRAFFIC_SURGE"
    DATABASE_INDEX_REGRESSION = "DATABASE_INDEX_REGRESSION"
    REPLICA_LAG = "REPLICA_LAG"


class LifecycleState(str, Enum):
    """Incident investigation lifecycle state machine."""

    RECEIVED = "RECEIVED"
    COLLECTING = "COLLECTING"
    RECONCILING = "RECONCILING"
    HYPOTHESIZING = "HYPOTHESIZING"
    SCORING = "SCORING"
    REPORTING = "REPORTING"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"


class EvidenceStrengthBand(str, Enum):
    """Evaluated confidence strength band for a root cause hypothesis."""

    STRONG = "STRONG"  # Net score >= 12 with support from >= 2 source groups
    MODERATE = "MODERATE"  # Net score 6-11 with direct evidence or multiple groups
    WEAK = "WEAK"  # Net score 1-5
    UNSUPPORTED = "UNSUPPORTED"  # Net score 0


# ---------------------------------------------------------------------------
# Core Domain Entities (Immutable Observation Record)
# ---------------------------------------------------------------------------


class FaultReport(BaseModel):
    """Initial incident alert received from operations."""

    source: str
    severity: str
    headline: str
    reported_at: datetime
    details: str


class EvidenceObservation(BaseModel):
    """An immutable, ledger-assigned diagnostic observation."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Stable ID assigned sequentially by the ledger (EV-001, EV-002...)")
    source_group: SourceGroup
    source: str
    component: ComponentEnum
    signal: str
    dimension: HealthDimension
    status: HealthStatus
    value: float
    unit: str
    observed_at: datetime
    window_start: datetime
    window_end: datetime
    scope: str
    reliability: ReliabilityLevel
    details: str


class Conflict(BaseModel):
    """A detected contradiction, scope tension, or temporal conflict between independent sources."""

    id: str
    conflict_type: ConflictType
    component: ComponentEnum
    evidence_ids: list[str]
    headline: str
    description: str
    operational_implication: str


# ---------------------------------------------------------------------------
# LLM / Gemini Communication Schemas
# ---------------------------------------------------------------------------


class DiagnosticToolName(str, Enum):
    """Supported diagnostic tool names."""

    QUERY_TELEMETRY = "query_telemetry"
    RUN_HEALTH_PROBES = "run_health_probes"
    FETCH_OPERATIONAL_EVENTS = "fetch_operational_events"


class DiagnosticToolCall(BaseModel):
    """A diagnostic tool invocation request from Gemini."""

    tool_name: DiagnosticToolName = Field(
        ..., description="Tool name: query_telemetry, run_health_probes, fetch_operational_events"
    )
    component: Optional[ComponentEnum] = Field(default=None, description="Optional target component to focus on")
    dimension: Optional[HealthDimension] = Field(default=None, description="Optional target dimension to focus on")
    reasoning: str = Field(..., description="Why this diagnostic tool is requested next")


class DiagnosticActionBatch(BaseModel):
    """Batch of tool selections produced by Gemini in one investigation round."""

    tool_calls: list[DiagnosticToolCall] = Field(default_factory=list)
    investigation_complete: bool = Field(
        default=False, description="Set to true when sufficient multi-source evidence has been collected"
    )
    summary: Optional[str] = Field(default=None, description="High-level reasoning summary for this round")


class HypothesisDraft(BaseModel):
    """A root-cause candidate hypothesized by Gemini based on collected evidence."""

    cause_code: RootCauseCode
    summary: str
    causal_chain: list[str] = Field(
        ..., description="Step-by-step causal chain explaining how root cause led to observed symptoms"
    )
    supporting_evidence_ids: list[str] = Field(
        default_factory=list, description="IDs of observations that strictly match policy SUPPORTS signal rules"
    )
    opposing_evidence_ids: list[str] = Field(
        default_factory=list, description="IDs of observations that strictly match policy OPPOSES signal rules"
    )
    contextual_evidence_ids: list[str] = Field(
        default_factory=list,
        description="IDs of observations in the ledger providing context without affecting numeric cause score",
    )
    unresolved_uncertainties: list[str] = Field(default_factory=list)

    @field_validator("supporting_evidence_ids", "opposing_evidence_ids", "contextual_evidence_ids")
    @classmethod
    def validate_no_duplicate_ids(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("Evidence ID lists must not contain duplicate entries.")
        return v

    @model_validator(mode="after")
    def validate_no_cross_category_conflicts(self) -> "HypothesisDraft":
        sup_set = set(self.supporting_evidence_ids)
        opp_set = set(self.opposing_evidence_ids)
        ctx_set = set(self.contextual_evidence_ids)

        overlap_sup_opp = sup_set & opp_set
        if overlap_sup_opp:
            raise ValueError(
                f"Evidence IDs cannot be simultaneously supporting and opposing: {sorted(overlap_sup_opp)}"
            )

        overlap_ctx_sup = ctx_set & sup_set
        if overlap_ctx_sup:
            raise ValueError(
                f"Evidence IDs cannot be simultaneously contextual and supporting: {sorted(overlap_ctx_sup)}"
            )

        overlap_ctx_opp = ctx_set & opp_set
        if overlap_ctx_opp:
            raise ValueError(
                f"Evidence IDs cannot be simultaneously contextual and opposing: {sorted(overlap_ctx_opp)}"
            )

        return self


class HypothesisDraftSet(BaseModel):
    """Collection of candidate hypotheses synthesized by Gemini (strictly 2 to 4 unique causes)."""

    hypotheses: list[HypothesisDraft] = Field(..., min_length=2, max_length=4)

    @field_validator("hypotheses")
    @classmethod
    def validate_unique_causes(cls, v: list[HypothesisDraft]) -> list[HypothesisDraft]:
        codes = [h.cause_code for h in v]
        if len(codes) != len(set(codes)):
            raise ValueError("Draft hypotheses must not contain duplicate cause codes.")
        return v


class TradeOffComparison(BaseModel):
    """Explicit trade-off comparison between winning repair and top alternative."""

    alternative_strategy_id: str
    alternative_strategy_name: str
    alternative_advantage: str = Field(
        ..., description="What dimension makes the alternative tempting (e.g. faster recovery, lower operational cost)"
    )
    rejection_rationale: str = Field(
        ..., description="Why the winner is preferred despite the alternative's specific advantage"
    )


class AdvantageDimension(str, Enum):
    """Supported comparative advantage dimensions for alternative strategies."""

    SPEED = "speed"
    AFFORDABILITY = "affordability"
    SAFETY = "safety"
    NONE = "none"


class StructuredDecisionGrounding(BaseModel):
    """Authoritative deterministic ground truth underpinning the narrative explanation."""

    winning_strategy_id: str
    winning_strategy_name: str
    top_cause_code: RootCauseCode
    reconciled_conflict_ids: list[str] = Field(default_factory=list)
    reconciled_evidence_ids: list[str] = Field(default_factory=list)
    referenced_conflict_ids: list[str] = Field(default_factory=list)
    referenced_evidence_ids: list[str] = Field(default_factory=list)
    alternative_strategy_id: str
    alternative_strategy_name: str
    alternative_advantage_dimension: AdvantageDimension
    alternative_advantage_value: float
    winning_advantage_value: float
    rejection_risk_factor: str


class DecisionNarrativeDraft(BaseModel):
    """LLM-authored narrative explaining the incident and defending trade-offs without duplicating deterministic grounding."""

    executive_summary: str
    trade_off_comparison: TradeOffComparison
    grounded_contradiction_analysis: str = Field(
        ...,
        description="How specific conflicting signals are resolved in this decision",
    )
    remaining_uncertainties: list[str] = Field(default_factory=list)
    referenced_conflict_ids: list[str] = Field(
        default_factory=list, description="List of conflict IDs explicitly discussed in narrative (e.g. ['CONF-001'])"
    )
    referenced_evidence_ids: list[str] = Field(
        default_factory=list,
        description="List of evidence IDs explicitly discussed in narrative (e.g. ['EV-002', 'EV-003'])",
    )


class DecisionExplanation(BaseModel):
    """Written executive explanation defending the final deterministic strategy ranking."""

    executive_summary: str
    winning_strategy_id: str
    trade_off_comparison: TradeOffComparison
    grounded_contradiction_analysis: str = Field(
        ...,
        description="How specific conflicting signals (e.g. DB workload latency vs direct probe) are resolved in this decision",
    )
    remaining_uncertainties: list[str] = Field(default_factory=list)
    grounding: StructuredDecisionGrounding = Field(
        ..., description="Mandatory authoritative structured grounding underpinning the decision"
    )


# ---------------------------------------------------------------------------
# Evaluated Reasoning & Ranking Models
# ---------------------------------------------------------------------------


class ObservationEvidenceScore(BaseModel):
    """Detailed score breakdown of an observation's contribution to a hypothesis."""

    evidence_id: str
    source_group: SourceGroup
    component: ComponentEnum
    signal: str
    reliability_score: int
    freshness_score: int
    directness_score: int
    total_strength: int
    relationship: str  # "supports" | "opposes"
    is_dominant: bool = Field(
        default=True, description="True if this observation was selected as the dominant score for its source group"
    )
    excluded_by_source_cap: bool = Field(
        default=False,
        description="True if this observation was excluded from numeric total because another observation in the same source group had a higher or equal score",
    )


class EvaluatedHypothesis(BaseModel):
    """Deterministically scored hypothesis."""

    cause_code: RootCauseCode
    name: str
    summary: str
    causal_chain: list[str]
    supporting_observations: list[ObservationEvidenceScore]
    opposing_observations: list[ObservationEvidenceScore]
    contextual_evidence_ids: list[str] = Field(default_factory=list)
    supporting_score: float
    opposing_score: float
    net_evidence_score: float
    decision_weight: float = Field(
        ...,
        description="Policy-derived decision weight (%) calculated as net_evidence / total_positive_net_evidence. Not an empirical probability.",
    )
    strength_band: EvidenceStrengthBand
    unresolved_uncertainties: list[str]


class StrategyScore(BaseModel):
    """Evaluated repair strategy across four decision dimensions."""

    strategy_id: str
    name: str
    description: str
    expected_impact: float = Field(..., description="Weighted causal impact (60% weight)")
    safety: float = Field(..., description="Operational safety & failure blast radius (20% weight)")
    speed: float = Field(..., description="Mean time to recovery / execution velocity (15% weight)")
    affordability: float = Field(..., description="Resource & operational cost (5% weight)")
    final_score: float = Field(..., description="Overall calculated score (0-100 scale)")
    rank: int = Field(..., description="1-indexed deterministic rank position")
    risk_notes: str
    reversibility: str
    suggested_command: Optional[str] = None
    preconditions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------


class FaultlineError(Exception):
    """Base domain exception for Faultline."""

    pass


class ModelUnavailableError(FaultlineError):
    """Raised when both primary and fallback LLM models are unreachable/unavailable."""

    pass


class ModelAuthenticationError(FaultlineError):
    """Raised when upstream LLM authentication fails (401/invalid key)."""

    pass


class ModelRequestError(FaultlineError):
    """Raised when an invalid request (400) was sent to the model provider."""

    pass


class InvalidModelOutputError(FaultlineError):
    """Raised when the LLM outputs schema-invalid or ungrounded data that fails repair."""

    pass


class AnalysisTimeoutError(FaultlineError):
    """Raised when an individual model call or overall investigation analysis times out."""

    pass


class InsufficientEvidenceError(FaultlineError):
    """Raised when evidence collection fails to gather sufficient independent source groups."""

    pass


class OrchestratorError(FaultlineError):
    """Raised when an error occurs during investigation orchestration."""

    pass


class ValidationError(FaultlineError):
    """Raised when an incident report violates safety, provenance, or consistency invariants."""

    pass


# ---------------------------------------------------------------------------
# Policy Validation Configuration Models
# ---------------------------------------------------------------------------


class SignalRuleConfig(BaseModel):
    component: ComponentEnum
    dimension: HealthDimension
    statuses: list[HealthStatus] = Field(..., min_length=1)
    scope: Optional[str] = None
    relationship: str  # "supports" | "opposes"
    directness: str  # "direct" | "indirect" | "contextual"

    @field_validator("relationship")
    @classmethod
    def validate_relationship(cls, v: str) -> str:
        if v not in ("supports", "opposes"):
            raise ValueError(f"relationship must be 'supports' or 'opposes', got '{v}'")
        return v

    @field_validator("directness")
    @classmethod
    def validate_directness(cls, v: str) -> str:
        if v not in ("direct", "indirect", "contextual"):
            raise ValueError(f"directness must be 'direct', 'indirect', or 'contextual', got '{v}'")
        return v


class CauseConfig(BaseModel):
    name: str
    description: str
    signal_rules: list[SignalRuleConfig] = Field(..., min_length=1)


class StrategyConfig(BaseModel):
    id: str
    name: str
    description: str
    effectiveness_by_cause: dict[str, float]
    safety: float = Field(..., ge=0.0, le=100.0)
    speed: float = Field(..., ge=0.0, le=100.0)
    affordability: float = Field(..., ge=0.0, le=100.0)
    risk_notes: str
    reversibility: str
    suggested_command: str
    preconditions: list[str] = Field(default_factory=list)

    @field_validator("effectiveness_by_cause")
    @classmethod
    def validate_effectiveness(cls, v: dict[str, float]) -> dict[str, float]:
        allowed = {c.value for c in RootCauseCode}
        if set(v.keys()) != allowed:
            missing = allowed - set(v.keys())
            extra = set(v.keys()) - allowed
            raise ValueError(
                f"effectiveness_by_cause must define values for all root causes. Missing: {missing}, Extra: {extra}"
            )
        for cause, eff in v.items():
            if not (0.0 <= eff <= 100.0):
                raise ValueError(f"Effectiveness for '{cause}' must be in [0, 100], got {eff}")
        return v


class PolicyConfig(BaseModel):
    scoring_weights: dict[str, float]
    reliability_weights: dict[str, int]
    freshness_thresholds_seconds: dict[str, int]
    freshness_weights: dict[str, int]
    directness_weights: dict[str, int]
    cause_catalogue: dict[str, CauseConfig]
    strategies: dict[str, StrategyConfig]

    @field_validator("scoring_weights")
    @classmethod
    def validate_weights_sum(cls, v: dict[str, float]) -> dict[str, float]:
        required_keys = {"impact", "safety", "speed", "affordability"}
        if set(v.keys()) != required_keys:
            raise ValueError(f"scoring_weights must have exactly {required_keys}, got {set(v.keys())}")
        for k, val in v.items():
            if not (0.0 <= val <= 1.0):
                raise ValueError(f"scoring_weight '{k}' must be in [0, 1], got {val}")
        total = sum(v.values())
        if abs(total - 1.0) > 1e-4:
            raise ValueError(f"Scoring weights must sum to 1.0, got {total}")
        return v

    @field_validator("reliability_weights")
    @classmethod
    def validate_reliability_weights(cls, v: dict[str, int]) -> dict[str, int]:
        required_keys = {"verified", "aggregated", "advisory"}
        if set(v.keys()) != required_keys:
            raise ValueError(f"reliability_weights must have exactly {required_keys}, got {set(v.keys())}")
        for k, val in v.items():
            if val < 0:
                raise ValueError(f"reliability_weight '{k}' must be non-negative, got {val}")
        return v

    @field_validator("freshness_weights")
    @classmethod
    def validate_freshness_weights(cls, v: dict[str, int]) -> dict[str, int]:
        required_keys = {"current", "recent", "stale"}
        if set(v.keys()) != required_keys:
            raise ValueError(f"freshness_weights must have exactly {required_keys}, got {set(v.keys())}")
        for k, val in v.items():
            if val < 0:
                raise ValueError(f"freshness_weight '{k}' must be non-negative, got {val}")
        return v

    @field_validator("directness_weights")
    @classmethod
    def validate_directness_weights(cls, v: dict[str, int]) -> dict[str, int]:
        required_keys = {"direct", "indirect", "contextual"}
        if set(v.keys()) != required_keys:
            raise ValueError(f"directness_weights must have exactly {required_keys}, got {set(v.keys())}")
        for k, val in v.items():
            if val < 0:
                raise ValueError(f"directness_weight '{k}' must be non-negative, got {val}")
        return v

    @field_validator("freshness_thresholds_seconds")
    @classmethod
    def validate_freshness_thresholds(cls, v: dict[str, int]) -> dict[str, int]:
        required_keys = {"current_max", "recent_max"}
        if not required_keys.issubset(set(v.keys())):
            raise ValueError(f"freshness_thresholds_seconds must contain {required_keys}, got {set(v.keys())}")
        if v["current_max"] > v["recent_max"]:
            raise ValueError(f"current_max ({v['current_max']}) must be <= recent_max ({v['recent_max']})")
        return v

    @field_validator("cause_catalogue")
    @classmethod
    def validate_cause_catalogue(cls, v: dict[str, CauseConfig]) -> dict[str, CauseConfig]:
        expected_causes = {c.value for c in RootCauseCode}
        if set(v.keys()) != expected_causes:
            missing = expected_causes - set(v.keys())
            extra = set(v.keys()) - expected_causes
            raise ValueError(f"cause_catalogue must contain full catalogue. Missing: {missing}, Extra: {extra}")
        return v

    @field_validator("strategies")
    @classmethod
    def validate_strategies(cls, v: dict[str, StrategyConfig]) -> dict[str, StrategyConfig]:
        for k, strat in v.items():
            if strat.id != k:
                raise ValueError(f"Strategy key '{k}' does not match strategy.id '{strat.id}'")
        return v


# ---------------------------------------------------------------------------
# Execution Safety & Orchestration Models
# ---------------------------------------------------------------------------


class InvestigationTraceItem(BaseModel):
    """Single chronological step in the investigation timeline."""

    round_index: int
    action_type: str  # "tool_call" | "tool_result" | "state_change" | "model_reasoning" | "fallback" | "validation"
    timestamp: datetime
    tool_name: Optional[str] = None
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class ModelCallTrace(BaseModel):
    """Details of an individual LLM invocation within an investigation."""

    task: str
    model: str
    provider: Optional[str] = "google-gemini"
    fallback_used: bool = False
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


class ModelExecutionMetadata(BaseModel):
    """Provenance and runtime details of the LLM execution."""

    configured_primary_model: str
    configured_fallback_model: Optional[str] = None
    configured_openrouter_model: Optional[str] = None
    startup_resolved_model: Optional[str] = None
    startup_resolution_status: Optional[str] = None
    model_used: str
    provider_used: Optional[str] = None
    models_used: list[str] = Field(default_factory=list)
    thinking_level: str
    fallback_occurred: bool = False
    fallback_reason: Optional[str] = None
    runtime_fallback_occurred: bool = False
    runtime_fallback_reason: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    call_trace: list[ModelCallTrace] = Field(default_factory=list)


class ExecutionSafetySection(BaseModel):
    """Explicit safety boundary assuring no unapproved mutations occur."""

    execution_status: str = "not_executed"
    operator_approval_required: bool = True
    suggested_command: str
    safety_preconditions: list[str]


class AnalysisResult(BaseModel):
    """Complete, validated incident analysis report."""

    run_id: str
    scenario_id: str
    state: LifecycleState
    incident: dict[str, Any]
    model_execution: ModelExecutionMetadata
    investigation_trace: list[InvestigationTraceItem]
    evidence: list[EvidenceObservation]
    conflicts: list[Conflict]
    hypotheses: list[EvaluatedHypothesis]
    strategy_ranking: list[StrategyScore]
    recommendation: DecisionExplanation
    execution: ExecutionSafetySection
    validation_passed: bool


class ScenarioMetadata(BaseModel):
    """Summary of a scenario available in the catalogue."""

    id: str
    title: str
    description: str
    affected_components: list[ComponentEnum]


class AnalyzeRequest(BaseModel):
    """Request payload for /api/analyze."""

    scenario_id: str = Field(
        default="cache_invalidation_lag",
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Identifier of the scenario fixture to diagnose.",
    )


class GenerateIncidentRequest(BaseModel):
    """Request payload for /api/incidents/generate."""

    seed: Optional[int] = Field(default=None, description="Optional deterministic seed for reproducibility.")
    archetype: Optional[str] = Field(default=None, description="Optional failure archetype identifier.")


class GenerateIncidentResponse(BaseModel):
    """Response payload for /api/incidents/generate."""

    id: str
    title: str
    description: str
    affected_components: list[str]
    incident_at: str
    is_dynamic: bool = True

