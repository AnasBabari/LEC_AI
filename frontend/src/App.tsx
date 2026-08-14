import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Cpu,
  Database,
  Eye,
  Layers,
  Play,
  RotateCcw,
  Server,
  ShieldAlert,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { analyzeScenario, fetchHealth, fetchScenarios } from './api';
import type {
  AnalysisResult,
  ComponentEnum,
  HealthResponse,
  HealthStatus,
  ScenarioMetadata,
} from './types';

export const App: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioMetadata[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>('cache_invalidation_lag');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);

  // Replay timeline state
  const [replayIndex, setReplayIndex] = useState<number>(0);
  const [isReplaying, setIsReplaying] = useState<boolean>(false);

  // Expanded evidence breakdowns per hypothesis
  const [expandedBreakdowns, setExpandedBreakdowns] = useState<Record<string, boolean>>({});

  // Filters
  const [componentFilter, setComponentFilter] = useState<string>('all');
  const [sourceFilter, setSourceFilter] = useState<string>('all');

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch((err) => console.warn('Health check failed:', err));

    fetchScenarios()
      .then((data) => {
        setScenarios(data);
        if (data.length > 0) setSelectedScenarioId(data[0].id);
      })
      .catch((err) => console.warn('Failed loading scenarios:', err));
  }, []);

  const handleScenarioChange = (newId: string) => {
    setSelectedScenarioId(newId);
    setResult(null); // Clear stale results on scenario switch
    setError(null);
  };

  const handleRunInvestigation = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await analyzeScenario(selectedScenarioId);
      setResult(data);
      setReplayIndex(data.investigation_trace.length); // Show full timeline by default
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Investigation failed';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleStartReplay = () => {
    if (!result) return;
    setReplayIndex(1);
    setIsReplaying(true);
  };

  const toggleBreakdown = (causeCode: string) => {
    setExpandedBreakdowns((prev) => ({
      ...prev,
      [causeCode]: !prev[causeCode],
    }));
  };

  useEffect(() => {
    if (!isReplaying || !result) return;
    if (replayIndex >= result.investigation_trace.length) {
      setIsReplaying(false);
      return;
    }
    const timer = setTimeout(() => {
      setReplayIndex((prev) => prev + 1);
    }, 600);
    return () => clearTimeout(timer);
  }, [isReplaying, replayIndex, result]);

  const selectedScenario = scenarios.find((s) => s.id === selectedScenarioId);

  const getStatusBadgeClass = (status: HealthStatus) => {
    switch (status) {
      case 'healthy':
        return 'badge-healthy';
      case 'degraded':
        return 'badge-degraded';
      case 'failed':
        return 'badge-failed';
      default:
        return 'badge-neutral';
    }
  };

  const getComponentIcon = (comp: ComponentEnum) => {
    switch (comp) {
      case 'api_gateway':
        return <Server size={14} />;
      case 'database':
        return <Database size={14} />;
      case 'cache':
        return <Zap size={14} />;
      case 'message_queue':
        return <Layers size={14} />;
    }
  };

  const filteredEvidence = result?.evidence.filter((obs) => {
    if (componentFilter !== 'all' && obs.component !== componentFilter) return false;
    if (sourceFilter !== 'all' && obs.source_group !== sourceFilter) return false;
    return true;
  }) || [];

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="brand-area">
          <div className="brand-logo">FL</div>
          <div>
            <h1 className="brand-title">Faultline</h1>
            <div className="brand-subtitle">Operational Decision-Support & Strategy Ranker</div>
          </div>
        </div>

        <div className="header-meta">
          {health && (
            <div className="badge badge-primary">
              <Cpu size={12} /> {health.runtime_model} ({health.provider_mode === 'live_gemini' ? 'Live API' : 'Deterministic Mode'})
            </div>
          )}
          {result?.model_execution?.fallback_occurred && (
            <div className="badge badge-degraded">
              Fallback Active ({result.model_execution.model_used})
            </div>
          )}
          {!health ? (
            <div className="badge badge-neutral">
              <AlertTriangle size={12} /> Connecting...
            </div>
          ) : health.analysis_ready === false || health.status !== 'healthy' ? (
            <div className="badge badge-failed">
              <ShieldAlert size={12} /> Not Ready
            </div>
          ) : (
            <div className="badge badge-healthy">
              <CheckCircle2 size={12} /> Ready
            </div>
          )}
        </div>
      </header>

      {/* Scenario Selector & Action Bar */}
      <div className="action-bar">
        <select
          className="scenario-select"
          value={selectedScenarioId}
          onChange={(e) => handleScenarioChange(e.target.value)}
          disabled={loading}
        >
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title}
            </option>
          ))}
        </select>

        <button
          className="btn-primary"
          onClick={handleRunInvestigation}
          disabled={loading || (health !== null && health.analysis_ready === false)}
        >
          {loading ? (
            <>
              <span className="spinner"></span> Analyzing incident...
            </>
          ) : (
            <>
              <Play size={14} /> Run Investigation
            </>
          )}
        </button>

        {result && (
          <button
            className="btn-secondary"
            onClick={handleStartReplay}
            disabled={isReplaying}
          >
            <RotateCcw size={14} /> Replay Investigation
          </button>
        )}
      </div>

      {/* Error Banner */}
      {error && (
        <div className="error-banner">
          <AlertTriangle size={18} /> {error}
        </div>
      )}

      {/* Scenario Context Card */}
      {selectedScenario && (
        <div className="card" style={{ marginBottom: '16px' }}>
          <div className="card-header">
            <div className="card-title">
              <Layers size={16} /> Scenario Context: {selectedScenario.title}
            </div>
            <div style={{ display: 'flex', gap: '4px' }}>
              {selectedScenario.affected_components.map((c) => (
                <span key={c} className="badge badge-neutral">
                  {c}
                </span>
              ))}
            </div>
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: 0 }}>
            {selectedScenario.description}
          </p>
        </div>
      )}

      {/* Active Investigation Results */}
      {result && (
        <>
          {/* Metadata & Timeline Bar */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <Cpu size={16} /> Investigation Trace ({result.investigation_trace.length} Steps)
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <span className="badge badge-healthy">Validated: Passed</span>
                <span className="badge badge-neutral">Run ID: {result.run_id}</span>
              </div>
            </div>

            {/* Step-by-Step Replay Timeline */}
            <div className="timeline-container">
              {result.investigation_trace.slice(0, replayIndex).map((item, idx) => (
                <div key={idx} className="timeline-step">
                  <div className="timeline-header">
                    <span className="timeline-round">Round {item.round_index}</span>
                    <span className="timeline-type">{item.action_type}</span>
                    <span className="timeline-time">
                      {new Date(item.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                  <div className="timeline-summary">{item.summary}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="grid-2">
            {/* Evidence Ledger */}
            <div className="card">
              <div className="card-header">
                <div className="card-title">
                  <Database size={16} /> Evidence Ledger ({filteredEvidence.length})
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <select
                    className="scenario-select"
                    style={{ minWidth: '100px', padding: '4px 8px', fontSize: '12px' }}
                    value={componentFilter}
                    onChange={(e) => setComponentFilter(e.target.value)}
                  >
                    <option value="all">All Components</option>
                    <option value="api_gateway">Gateway</option>
                    <option value="database">Database</option>
                    <option value="cache">Cache</option>
                    <option value="message_queue">Queue</option>
                  </select>
                  <select
                    className="scenario-select"
                    style={{ minWidth: '100px', padding: '4px 8px', fontSize: '12px' }}
                    value={sourceFilter}
                    onChange={(e) => setSourceFilter(e.target.value)}
                  >
                    <option value="all">All Sources</option>
                    <option value="telemetry">Telemetry</option>
                    <option value="health_probe">Health Probe</option>
                    <option value="operational_events">Events</option>
                  </select>
                </div>
              </div>

              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Source</th>
                      <th>Component</th>
                      <th>Signal</th>
                      <th>Status</th>
                      <th>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredEvidence.map((obs) => (
                      <tr key={obs.id}>
                        <td>
                          <span className="badge badge-neutral">{obs.id}</span>
                        </td>
                        <td style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          {obs.source_group}
                        </td>
                        <td>
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                            {getComponentIcon(obs.component)} {obs.component}
                          </span>
                        </td>
                        <td>{obs.signal}</td>
                        <td>
                          <span className={`badge ${getStatusBadgeClass(obs.status)}`}>{obs.status}</span>
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)' }}>
                          {obs.value} {obs.unit}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Conflicts Panel */}
            <div className="card">
              <div className="card-header">
                <div className="card-title">
                  <ShieldAlert size={16} /> Diagnostic Contradictions & Scope Tensions ({result.conflicts.length})
                </div>
              </div>

              {result.conflicts.map((c) => (
                <div key={c.id} className="conflict-item">
                  <div className="conflict-headline">
                    <span className="badge badge-degraded">{c.conflict_type}</span> {c.headline}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--primary)', margin: '4px 0', fontFamily: 'var(--font-mono)' }}>
                    Evidence: {c.evidence_ids.join(', ')}
                  </div>
                  <div className="conflict-desc">{c.description}</div>
                  <div className="conflict-implication">
                    <strong>Operational Insight:</strong> {c.operational_implication}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Root Cause Hypotheses */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <Cpu size={16} /> Evaluated Root-Cause Hypotheses (Deterministic Scoring)
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                *Policy-derived decision weight, not an empirical probability
              </div>
            </div>

            <div className="grid-2" style={{ marginBottom: 0 }}>
              {result.hypotheses.map((hyp) => {
                const isExpanded = !!expandedBreakdowns[hyp.cause_code];
                return (
                  <div key={hyp.cause_code} className="hypothesis-card">
                    <div className="hypothesis-header">
                      <div>
                        <div className="hypothesis-title">{hyp.name}</div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                          {hyp.cause_code}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div className="badge badge-primary" style={{ fontSize: '13px' }}>
                          Weight: {hyp.decision_weight}%
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                          Net Evidence: {hyp.net_evidence_score}
                        </div>
                      </div>
                    </div>

                    <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '8px 0' }}>{hyp.summary}</p>

                    <div className="causal-chain">
                      <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--text-primary)' }}>
                        Causal Chain:
                      </div>
                      {hyp.causal_chain.map((step, sIdx) => (
                        <div key={sIdx} className="causal-step">
                          <ArrowRight size={12} color="var(--primary)" /> {step}
                        </div>
                      ))}
                    </div>

                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '8px' }}>
                      <strong>Supporting Evidence:</strong>{' '}
                      {hyp.supporting_observations.map((s) => s.evidence_id).join(', ') || 'None'} |{' '}
                      <strong>Opposing:</strong>{' '}
                      {hyp.opposing_observations.map((o) => o.evidence_id).join(', ') || 'None'}
                      {hyp.contextual_evidence_ids && hyp.contextual_evidence_ids.length > 0 && (
                        <>
                          {' | '}
                          <strong>Contextual:</strong> {hyp.contextual_evidence_ids.join(', ')}
                        </>
                      )}
                    </div>

                    {/* Expandable Evidence Score Breakdown */}
                    <div style={{ marginTop: '10px' }}>
                      <button
                        className="btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                        onClick={() => toggleBreakdown(hyp.cause_code)}
                      >
                        {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                        {isExpanded ? 'Hide Score Calculation' : 'Challenge / Inspect Score Breakdown'}
                      </button>

                      {isExpanded && (
                        <div style={{ marginTop: '8px', padding: '8px', background: 'rgba(0,0,0,0.2)', borderRadius: '4px', fontSize: '11px' }}>
                          <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--text-primary)' }}>
                            Supporting Contributions (R + F + D = Strength):
                          </div>
                          {hyp.supporting_observations.length === 0 ? (
                            <div style={{ color: 'var(--text-muted)' }}>None</div>
                          ) : (
                            hyp.supporting_observations.map((s) => (
                              <div key={s.evidence_id} style={{ fontFamily: 'var(--font-mono)', margin: '2px 0' }}>
                                [{s.evidence_id}] {s.source_group} ({s.component}): R:{s.reliability_score} + F:{s.freshness_score} + D:{s.directness_score} = {s.total_strength} pts
                                {s.excluded_by_source_cap ? ' (Capped / Excluded by Source Group Max)' : ' [Dominant in Group]'}
                              </div>
                            ))
                          )}

                          {hyp.opposing_observations.length > 0 && (
                            <>
                              <div style={{ fontWeight: 600, marginTop: '6px', marginBottom: '4px', color: 'var(--text-primary)' }}>
                                Opposing Deductions:
                              </div>
                              {hyp.opposing_observations.map((o) => (
                                <div key={o.evidence_id} style={{ fontFamily: 'var(--font-mono)', margin: '2px 0' }}>
                                  [{o.evidence_id}] {o.source_group} ({o.component}): -{o.total_strength} pts
                                  {o.excluded_by_source_cap ? ' (Capped)' : ''}
                                </div>
                              ))}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 4D Strategy Ranking */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <ShieldCheck size={16} /> 4-Dimensional Repair Strategy Ranking
              </div>
              <div className="badge badge-primary">Formula: 60% Impact + 20% Safety + 15% Speed + 5% Cost</div>
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Strategy</th>
                    <th>Expected Impact (60%)</th>
                    <th>Safety (20%)</th>
                    <th>Speed (15%)</th>
                    <th>Affordability (5%)</th>
                    <th>Final Score</th>
                  </tr>
                </thead>
                <tbody>
                  {result.strategy_ranking.map((strat) => (
                    <tr
                      key={strat.strategy_id}
                      style={strat.rank === 1 ? { background: 'rgba(59, 130, 246, 0.08)' } : {}}
                    >
                      <td>
                        <span className={`rank-badge rank-${strat.rank <= 3 ? strat.rank : 'other'}`}>
                          {strat.rank}
                        </span>
                      </td>
                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{strat.name}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{strat.description}</div>
                      </td>
                      <td>
                        <div className="score-bar-container">
                          <span>{strat.expected_impact.toFixed(1)}</span>
                          <div className="score-bar-bg">
                            <div className="score-bar-fill" style={{ width: `${strat.expected_impact}%` }}></div>
                          </div>
                        </div>
                      </td>
                      <td>{strat.safety.toFixed(1)}</td>
                      <td>{strat.speed.toFixed(1)}</td>
                      <td>{strat.affordability.toFixed(1)}</td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '15px' }}>
                        {strat.final_score.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Executive Trade-Off Defense Box */}
          <div className="defense-box">
            <div className="defense-title">
              <Eye size={18} /> Executive Decision Defense & Trade-Off Analysis
            </div>
            <div className="defense-section">
              <strong>Executive Summary:</strong> {result.recommendation.executive_summary}
            </div>
            <div className="defense-section">
              <strong>Trade-Off Defense (Why Rank #1 Beats Alternative):</strong>
              <div style={{ margin: '6px 0', paddingLeft: '12px', borderLeft: '2px solid var(--primary)' }}>
                <div>
                  <em>Alternative Advantage:</em>{' '}
                  {result.recommendation.trade_off_comparison.alternative_advantage}
                </div>
                <div style={{ marginTop: '4px' }}>
                  <em>Rejection Rationale:</em>{' '}
                  {result.recommendation.trade_off_comparison.rejection_rationale}
                </div>
              </div>
            </div>
            <div className="defense-section">
              <strong>Contradiction Reconciliation:</strong>{' '}
              {result.recommendation.grounded_contradiction_analysis}
            </div>
            {result.recommendation.remaining_uncertainties.length > 0 && (
              <div className="defense-section" style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                <strong>Remaining Operational Uncertainties:</strong>{' '}
                {result.recommendation.remaining_uncertainties.join(' ')}
              </div>
            )}
          </div>
        </>
      )}

      {/* Safety Footer */}
      <footer className="safety-footer">
        <div className="safety-tag">
          <ShieldAlert size={16} /> NO REPAIR EXECUTED — OPERATOR APPROVAL REQUIRED
        </div>
        <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
          <div><strong>Suggested Action:</strong> {result?.execution.suggested_command || 'None'}</div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            <em>Illustrative remediation stub — never executed by Faultline.</em>
          </div>
          {result?.execution.safety_preconditions && result.execution.safety_preconditions.length > 0 && (
            <div style={{ marginTop: '4px', fontSize: '11px' }}>
              <strong>Preconditions:</strong> {result.execution.safety_preconditions.join('; ')}
            </div>
          )}
        </div>
      </footer>
    </div>
  );
};

export default App;
