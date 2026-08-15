import React, { useState } from 'react';
import {
  Cpu,
  Layers,
  Info,
  CheckCircle2,
  XCircle,
  Calculator,
  ChevronDown,
  ChevronUp,
  ArrowRight,
} from 'lucide-react';
import type { EvaluatedHypothesis } from '../types';
import { StatusBadge } from './StatusBadge';

interface HypothesesInspectorProps {
  hypotheses: EvaluatedHypothesis[];
  onSelectEvidence?: (evidenceId: string) => void;
}

export const HypothesesInspector: React.FC<HypothesesInspectorProps> = ({
  hypotheses,
  onSelectEvidence,
}) => {
  const [expandedBreakdownCodes, setExpandedBreakdownCodes] = useState<Record<string, boolean>>({});

  const toggleBreakdown = (code: string) => {
    setExpandedBreakdownCodes((prev) => ({ ...prev, [code]: !prev[code] }));
  };

  return (
    <div className="card hypotheses-main-card">
      <div className="card-header">
        <div className="card-title">
          <div className="title-icon-box text-cyan">
            <Cpu size={16} />
          </div>
          <div>
            <span className="title-text">What Could Be Causing This?</span>
            <span className="title-subtext">
              ({hypotheses.length} {hypotheses.length === 1 ? 'possible cause' : 'possible causes'} evaluated)
            </span>
          </div>
        </div>
      </div>

      <div className="hypotheses-grid">
        {hypotheses.map((hyp) => {
          const isWinner = hyp.strength_band === 'STRONG';
          const isExpanded = !!expandedBreakdownCodes[hyp.cause_code];

          return (
            <div
              key={hyp.cause_code}
              className={`hypothesis-card-enhanced ${isWinner ? 'hypo-winner-border' : ''}`}
            >
              {/* Card Top: Name, Confidence badge, Likelihood % */}
              <div className="hypo-top-row">
                <div className="hypo-name-row">
                  <h3 className="hypo-name">{hyp.name}</h3>
                  <StatusBadge status={hyp.strength_band} size="sm" />
                </div>

                <div className="hypo-scores-wrap">
                  <span className="hypo-weight-pill font-mono">
                    <span className="weight-label">Likelihood:</span>
                    <span className="weight-val">{hyp.decision_weight.toFixed(1)}%</span>
                  </span>
                </div>
              </div>

              {/* Confidence Band Bar */}
              <div className="hypo-weight-track">
                <div
                  className={`hypo-weight-fill ${
                    isWinner ? 'fill-dominant' : hyp.decision_weight > 0 ? 'fill-secondary' : 'fill-muted'
                  }`}
                  style={{ width: `${Math.max(2, hyp.decision_weight)}%` }}
                />
              </div>

              {/* Summary */}
              <p className="hypo-summary">{hyp.summary}</p>

              {/* Chain of Events */}
              <div className="causal-chain-box">
                <div className="causal-chain-header">
                  <Layers size={12} /> How it happens:
                </div>
                <div className="causal-chain-flow">
                  {hyp.causal_chain.map((step, sIdx) => (
                    <React.Fragment key={sIdx}>
                      <div className="causal-step-node">
                        <span className="step-num font-mono">{sIdx + 1}</span>
                        <span className="step-text">{step}</span>
                      </div>
                      {sIdx < hyp.causal_chain.length - 1 && (
                        <ArrowRight size={13} className="causal-arrow" />
                      )}
                    </React.Fragment>
                  ))}
                </div>
              </div>

              {/* Evidence For & Against */}
              <div className="citations-bar">
                <div className="citation-group">
                  <span className="citation-label">Evidence for:</span>
                  {hyp.supporting_observations.length === 0 ? (
                    <span className="text-muted text-xs">None</span>
                  ) : (
                    hyp.supporting_observations.map((s) => (
                      <button
                        key={s.evidence_id}
                        className="citation-chip chip-support font-mono"
                        onClick={() => onSelectEvidence?.(s.evidence_id)}
                        title={`[+] ${s.evidence_id} (${s.signal}): +${s.total_strength} pts from ${s.source_group}`}
                      >
                        +{s.evidence_id}
                      </button>
                    ))
                  )}
                </div>

                <div className="citation-group">
                  <span className="citation-label">Evidence against:</span>
                  {hyp.opposing_observations.length === 0 ? (
                    <span className="text-muted text-xs">None</span>
                  ) : (
                    hyp.opposing_observations.map((o) => (
                      <button
                        key={o.evidence_id}
                        className="citation-chip chip-oppose font-mono"
                        onClick={() => onSelectEvidence?.(o.evidence_id)}
                        title={`[-] ${o.evidence_id} (${o.signal}): -${o.total_strength} pts deduction from ${o.source_group}`}
                      >
                        -{o.evidence_id}
                      </button>
                    ))
                  )}
                </div>

                {hyp.contextual_evidence_ids && hyp.contextual_evidence_ids.length > 0 && (
                  <div className="citation-group">
                    <span className="citation-label">Background info:</span>
                    {hyp.contextual_evidence_ids.map((cid) => (
                      <button
                        key={cid}
                        className="citation-chip chip-context font-mono"
                        onClick={() => onSelectEvidence?.(cid)}
                      >
                        {cid}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Expandable Score Breakdown (technical - hidden by default) */}
              <div className="score-inspector-section">
                <button
                  className="inspector-toggle-btn font-mono"
                  onClick={() => toggleBreakdown(hyp.cause_code)}
                >
                  <Calculator size={13} />
                  <span>{isExpanded ? 'Hide scoring details' : 'How was this scored?'}</span>
                  {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </button>

                {isExpanded && (
                  <div className="inspector-breakdown-panel">
                    <div className="formula-header-callout font-mono">
                      <span>Each piece of evidence is scored on Reliability + Freshness + Directness</span>
                      <span>Only the strongest evidence per data source counts</span>
                    </div>

                    {/* Supporting Evidence Table */}
                    <div className="breakdown-subtable">
                      <div className="subtable-title font-mono text-emerald">
                        <CheckCircle2 size={12} /> Evidence supporting this theory (+{hyp.supporting_score} points):
                      </div>

                      {hyp.supporting_observations.length === 0 ? (
                        <div className="text-muted text-xs font-mono">No supporting evidence found.</div>
                      ) : (
                        <div className="math-table-wrap">
                          <table className="math-table font-mono">
                            <thead>
                              <tr>
                                <th>Evidence</th>
                                <th>Data Source</th>
                                <th>System</th>
                                <th>Reliability</th>
                                <th>Freshness</th>
                                <th>Directness</th>
                                <th>Score</th>
                                <th>Status</th>
                              </tr>
                            </thead>
                            <tbody>
                              {hyp.supporting_observations.map((obs) => (
                                <tr key={obs.evidence_id} className={obs.excluded_by_source_cap ? 'row-capped' : 'row-dominant'}>
                                  <td>
                                    <button
                                      className="cell-id-btn"
                                      onClick={() => onSelectEvidence?.(obs.evidence_id)}
                                    >
                                      {obs.evidence_id}
                                    </button>
                                  </td>
                                  <td>{obs.source_group}</td>
                                  <td>{obs.component}</td>
                                  <td>+{obs.reliability_score}</td>
                                  <td>+{obs.freshness_score}</td>
                                  <td>+{obs.directness_score}</td>
                                  <td className="font-bold text-emerald">+{obs.total_strength}</td>
                                  <td>
                                    {obs.excluded_by_source_cap ? (
                                      <span className="cap-badge cap-excluded">Capped (duplicate source)</span>
                                    ) : (
                                      <span className="cap-badge cap-dominant">Counted</span>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>

                    {/* Opposing Evidence Table */}
                    {hyp.opposing_observations.length > 0 && (
                      <div className="breakdown-subtable mt-3">
                        <div className="subtable-title font-mono text-rose">
                          <XCircle size={12} /> Evidence against this theory (-{hyp.opposing_score} points):
                        </div>

                        <div className="math-table-wrap">
                          <table className="math-table font-mono">
                            <thead>
                              <tr>
                                <th>Evidence</th>
                                <th>Data Source</th>
                                <th>System</th>
                                <th>Reliability</th>
                                <th>Freshness</th>
                                <th>Directness</th>
                                <th>Deduction</th>
                                <th>Status</th>
                              </tr>
                            </thead>
                            <tbody>
                              {hyp.opposing_observations.map((obs) => (
                                <tr key={obs.evidence_id} className="row-deduction">
                                  <td>
                                    <button
                                      className="cell-id-btn"
                                      onClick={() => onSelectEvidence?.(obs.evidence_id)}
                                    >
                                      {obs.evidence_id}
                                    </button>
                                  </td>
                                  <td>{obs.source_group}</td>
                                  <td>{obs.component}</td>
                                  <td>{obs.reliability_score}</td>
                                  <td>{obs.freshness_score}</td>
                                  <td>{obs.directness_score}</td>
                                  <td className="font-bold text-rose">-{obs.total_strength}</td>
                                  <td>
                                    {obs.excluded_by_source_cap ? (
                                      <span className="cap-badge cap-excluded">Capped</span>
                                    ) : (
                                      <span className="cap-badge cap-dominant">Counted</span>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {/* Score Summary */}
                    <div className="math-summary-box font-mono">
                      <span>Net Score: ({hyp.supporting_score} for - {hyp.opposing_score} against) = {hyp.net_evidence_score} points</span>
                      <span>Assessed Likelihood: {hyp.decision_weight}%</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Open Questions */}
              {hyp.unresolved_uncertainties.length > 0 && (
                <div className="hypo-uncertainties-box">
                  <div className="uncertainties-header">
                    <Info size={11} className="text-muted" /> What we still don&apos;t know:
                  </div>
                  <ul className="uncertainties-list">
                    {hyp.unresolved_uncertainties.map((u, uIdx) => (
                      <li key={uIdx}>{u}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
