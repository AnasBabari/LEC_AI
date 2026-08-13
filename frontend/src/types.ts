export type SourceGroup = 'telemetry' | 'health_probe' | 'operational_events';
export type ComponentEnum = 'api_gateway' | 'database' | 'cache' | 'message_queue';
export type HealthDimension = 'latency' | 'availability' | 'freshness' | 'throughput' | 'backlog';
export type HealthStatus = 'healthy' | 'degraded' | 'failed' | 'informational' | 'unknown';
export type ReliabilityLevel = 'verified' | 'aggregated' | 'advisory';
export type ConflictType = 'DIRECT_CONTRADICTION' | 'SCOPE_TENSION' | 'TEMPORAL_CONFLICT';
export type RootCauseCode =
  | 'CACHE_INVALIDATION_CONSUMER_STALLED'
  | 'DATABASE_CAPACITY_DEGRADATION'
  | 'CACHE_NODE_FAILURE'
  | 'TRAFFIC_SURGE'
  | 'DATABASE_INDEX_REGRESSION'
  | 'REPLICA_LAG';

export interface EvidenceObservation {
  id: string;
  source_group: SourceGroup;
  source: string;
  component: ComponentEnum;
  signal: string;
  dimension: HealthDimension;
  status: HealthStatus;
  value: number;
  unit: string;
  observed_at: string;
  window_start: string;
  window_end: string;
  scope: string;
  reliability: ReliabilityLevel;
  details: string;
}

export interface Conflict {
  id: string;
  conflict_type: ConflictType;
  component: ComponentEnum;
  evidence_ids: string[];
  headline: string;
  description: string;
  operational_implication: string;
}

export interface ObservationEvidenceScore {
  evidence_id: string;
  source_group: SourceGroup;
  component: ComponentEnum;
  signal: string;
  reliability_score: number;
  freshness_score: number;
  directness_score: number;
  total_strength: number;
  relationship: string;
  is_capped: boolean;
}

export interface EvaluatedHypothesis {
  cause_code: RootCauseCode;
  name: string;
  summary: string;
  causal_chain: string[];
  supporting_observations: ObservationEvidenceScore[];
  opposing_observations: ObservationEvidenceScore[];
  supporting_score: number;
  opposing_score: number;
  net_evidence_score: number;
  decision_weight: number;
  strength_band: 'STRONG' | 'MODERATE' | 'WEAK' | 'UNSUPPORTED';
  unresolved_uncertainties: string[];
}

export interface StrategyScore {
  strategy_id: string;
  name: string;
  description: string;
  expected_impact: number;
  safety: number;
  speed: number;
  affordability: number;
  final_score: number;
  rank: number;
  risk_notes: string;
  reversibility: string;
}

export interface TradeOffComparison {
  alternative_strategy_id: string;
  alternative_strategy_name: string;
  alternative_advantage: string;
  rejection_rationale: string;
}

export interface DecisionExplanation {
  executive_summary: string;
  winning_strategy_id: string;
  trade_off_comparison: TradeOffComparison;
  grounded_contradiction_analysis: string;
  remaining_uncertainties: string[];
}

export interface InvestigationTraceItem {
  round_index: number;
  action_type: string;
  timestamp: string;
  tool_name?: string;
  summary: string;
  details: Record<string, any>;
}

export interface ModelExecutionMetadata {
  configured_primary_model: string;
  configured_fallback_model?: string;
  model_used: string;
  thinking_level: string;
  fallback_occurred: boolean;
  fallback_reason?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
}

export interface ExecutionSafetySection {
  execution_status: string;
  operator_approval_required: boolean;
  suggested_command: string;
  safety_preconditions: string[];
}

export interface AnalysisResult {
  run_id: string;
  scenario_id: string;
  state: string;
  incident: {
    title: string;
    description: string;
    headline: string;
    severity: string;
    reported_at: string;
    details: string;
    affected_components: ComponentEnum[];
  };
  model_execution: ModelExecutionMetadata;
  investigation_trace: InvestigationTraceItem[];
  evidence: EvidenceObservation[];
  conflicts: Conflict[];
  hypotheses: EvaluatedHypothesis[];
  strategy_ranking: StrategyScore[];
  recommendation: DecisionExplanation;
  execution: ExecutionSafetySection;
  validation_passed: boolean;
}

export interface ScenarioMetadata {
  id: string;
  title: string;
  description: string;
  affected_components: ComponentEnum[];
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  gemini_configured: boolean;
  runtime_model: string;
}
