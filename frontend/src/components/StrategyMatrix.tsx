import React, { useState } from 'react';
import {
  ShieldCheck,
  Trophy,
  Zap,
  Shield,
  Gauge,
  DollarSign,
  AlertOctagon,
  ChevronDown,
  ChevronUp,
  Terminal,
  Copy,
  Check,
  Scale,
  ArrowRight,
} from 'lucide-react';
import type { StrategyScore, TradeOffComparison } from '../types';

interface StrategyMatrixProps {
  strategies: StrategyScore[];
  winningStrategyId?: string;
  tradeOff?: TradeOffComparison;
}

export const StrategyMatrix: React.FC<StrategyMatrixProps> = ({
  strategies,
  tradeOff,
}) => {
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null);
  const [showTradeOffModal, setShowTradeOffModal] = useState<boolean>(false);
  const [expandedStrategyId, setExpandedStrategyId] = useState<string | null>(null);

  const rank1Winner = strategies.find((s) => s.rank === 1);
  const alternativeStrategy = strategies.find(
    (s) => s.strategy_id === tradeOff?.alternative_strategy_id
  ) || strategies.find((s) => s.rank === 2);

  const handleCopy = (cmd: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(cmd);
    setCopiedCmd(cmd);
    setTimeout(() => setCopiedCmd(null), 2000);
  };

  const toggleStrategyDetails = (id: string) => {
    setExpandedStrategyId((prev) => (prev === id ? null : id));
  };

  const getReversibilityBadgeClass = (rev: string) => {
    const revLower = rev.toLowerCase();
    if (revLower.includes('high') || revLower.includes('immediate')) return 'badge-healthy';
    if (revLower.includes('moderate')) return 'badge-degraded';
    return 'badge-failed';
  };

  const getReversibilityLabel = (rev: string) => {
    const revLower = rev.toLowerCase();
    if (revLower.includes('high') || revLower.includes('immediate')) return 'Easy to undo';
    if (revLower.includes('moderate')) return 'Can be undone with effort';
    return 'Hard to reverse';
  };

  return (
    <div className="card strategy-main-card">
      <div className="card-header">
        <div className="card-title">
          <div className="title-icon-box text-primary">
            <ShieldCheck size={16} />
          </div>
          <div>
            <span className="title-text">Recommended Repair Strategies</span>
            <span className="title-subtext font-mono">
              ({strategies.length} options ranked by effectiveness, safety, speed, and cost)
            </span>
          </div>
        </div>
      </div>

      {/* Top Recommendation Banner */}
      {rank1Winner && (
        <div className="winner-spotlight-banner">
          <div className="winner-top-line">
            <div className="winner-badge-wrap">
              <span className="winner-tag">
                <Trophy size={14} className="trophy-icon" /> BEST OPTION
              </span>
              <span className="winner-rank-chip font-mono">#1 Recommended</span>
            </div>
            <div className="winner-score-display font-mono">
              <span className="score-label">Overall Score:</span>
              <span className="score-number">{rank1Winner.final_score.toFixed(1)}</span>
              <span className="score-max">/100</span>
            </div>
          </div>

          <div className="winner-body">
            <div className="winner-details">
              <h3 className="winner-title">{rank1Winner.name}</h3>
              <p className="winner-desc">{rank1Winner.description}</p>
              <div className="winner-attributes">
                <span className="attr-item">
                  <strong>Can it be undone?</strong>{' '}
                  <span className={`badge ${getReversibilityBadgeClass(rank1Winner.reversibility)}`}>
                    {getReversibilityLabel(rank1Winner.reversibility)}
                  </span>
                </span>
                <span className="attr-item">
                  <strong>Risk note:</strong> {rank1Winner.risk_notes}
                </span>
              </div>
            </div>

            {/* Compare with runner-up */}
            {tradeOff && alternativeStrategy && (
              <div className="winner-tradeoff-cta">
                <button
                  className="btn-tradeoff font-mono"
                  onClick={() => setShowTradeOffModal(!showTradeOffModal)}
                  aria-expanded={showTradeOffModal}
                >
                  <Scale size={13} />
                  <span>{showTradeOffModal ? 'Hide comparison' : 'Why not the runner-up?'}</span>
                </button>
              </div>
            )}
          </div>

          {/* Trade-Off Comparison */}
          {showTradeOffModal && tradeOff && alternativeStrategy && (
            <div className="tradeoff-inline-comparison">
              <div className="tradeoff-comp-header">
                <Scale size={14} className="text-amber" />
                <span>Why #{1} beats #{alternativeStrategy.rank}</span>
              </div>

              <div className="tradeoff-comp-grid">
                {/* Winner Card */}
                <div className="tradeoff-card card-winner">
                  <div className="tradeoff-card-tag text-emerald">
                    <Trophy size={12} /> Our recommendation
                  </div>
                  <h4 className="tradeoff-card-title">{rank1Winner.name}</h4>
                  <div className="tradeoff-metric-row font-mono">
                    <span>Impact: {rank1Winner.expected_impact.toFixed(1)}</span>
                    <span>Safety: {rank1Winner.safety.toFixed(1)}</span>
                    <span>Score: {rank1Winner.final_score.toFixed(1)}</span>
                  </div>
                  <p className="tradeoff-reason">
                    Addresses the root cause safely without creating new problems.
                  </p>
                </div>

                <div className="tradeoff-arrow-box">
                  <ArrowRight size={16} />
                  <span className="font-mono">BEATS</span>
                </div>

                {/* Alternative Card */}
                <div className="tradeoff-card card-alternative">
                  <div className="tradeoff-card-tag text-amber">
                    <AlertOctagon size={12} /> Runner-up: {tradeOff.alternative_strategy_name}
                  </div>
                  <h4 className="tradeoff-card-title">{alternativeStrategy.name}</h4>
                  <div className="tradeoff-metric-row font-mono">
                    <span className="text-emerald">Its advantage: {tradeOff.alternative_advantage}</span>
                  </div>
                  <div className="tradeoff-rejection-box">
                    <strong className="text-rose font-mono">Why we didn&apos;t pick it:</strong>
                    <p>{tradeOff.rejection_rationale}</p>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Desktop/Tablet Strategies Comparison Table */}
      <div className="strategy-table-container table-responsive-wrapper">
        <table className="data-table strategy-table">
          <thead>
            <tr>
              <th style={{ width: '60px' }}>Rank</th>
              <th>Strategy</th>
              <th style={{ minWidth: '130px' }}>
                <span className="th-dimension">
                  <Zap size={11} className="text-amber" /> Impact
                </span>
              </th>
              <th style={{ minWidth: '100px' }}>
                <span className="th-dimension">
                  <Shield size={11} className="text-emerald" /> Safety
                </span>
              </th>
              <th style={{ minWidth: '90px' }}>
                <span className="th-dimension">
                  <Gauge size={11} className="text-cyan" /> Speed
                </span>
              </th>
              <th style={{ minWidth: '90px' }}>
                <span className="th-dimension">
                  <DollarSign size={11} className="text-indigo" /> Cost
                </span>
              </th>
              <th style={{ minWidth: '100px' }}>Score</th>
              <th style={{ width: '80px' }}>Details</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((strat) => {
              const isWinner = strat.rank === 1;
              const isExpanded = expandedStrategyId === strat.strategy_id;

              return (
                <React.Fragment key={strat.strategy_id}>
                  <tr
                    className={`strategy-row ${isWinner ? 'row-rank-1' : ''}`}
                    onClick={() => toggleStrategyDetails(strat.strategy_id)}
                    tabIndex={0}
                    role="button"
                    aria-expanded={isExpanded}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        toggleStrategyDetails(strat.strategy_id);
                      }
                    }}
                  >
                    <td>
                      <span className={`rank-badge rank-${strat.rank <= 3 ? strat.rank : 'other'} font-mono`}>
                        {strat.rank === 1 ? <Trophy size={11} /> : strat.rank}
                      </span>
                    </td>
                    <td>
                      <div className="strategy-name-cell">
                        <span className="strat-name">{strat.name}</span>
                        {isWinner && <span className="winner-micro-tag">Best</span>}
                      </div>
                      <div className="strat-desc">{strat.description}</div>
                    </td>
                    <td>
                      <div className="score-dimension-cell font-mono">
                        <span className="dim-val">{strat.expected_impact.toFixed(1)}</span>
                        <div className="dim-bar-track" title={`Impact: ${strat.expected_impact.toFixed(1)}/100`}>
                          <div
                            className="dim-bar-fill fill-impact"
                            style={{ width: `${Math.max(2, strat.expected_impact)}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="score-dimension-cell font-mono">
                        <span className="dim-val">{strat.safety.toFixed(1)}</span>
                        <div className="dim-bar-track" title={`Safety: ${strat.safety.toFixed(1)}/100`}>
                          <div
                            className="dim-bar-fill fill-safety"
                            style={{ width: `${Math.max(2, strat.safety)}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="score-dimension-cell font-mono">
                        <span className="dim-val">{strat.speed.toFixed(1)}</span>
                        <div className="dim-bar-track" title={`Speed: ${strat.speed.toFixed(1)}/100`}>
                          <div
                            className="dim-bar-fill fill-speed"
                            style={{ width: `${Math.max(2, strat.speed)}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="score-dimension-cell font-mono">
                        <span className="dim-val">{strat.affordability.toFixed(1)}</span>
                        <div className="dim-bar-track" title={`Cost Affordability: ${strat.affordability.toFixed(1)}/100`}>
                          <div
                            className="dim-bar-fill fill-cost"
                            style={{ width: `${Math.max(2, strat.affordability)}%` }}
                          />
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="final-score-cell font-mono">
                        <span className={`final-score-val ${isWinner ? 'score-winner' : ''}`}>
                          {strat.final_score.toFixed(1)}
                        </span>
                      </div>
                    </td>
                    <td>
                      <button
                        className="btn-details-expand font-mono"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleStrategyDetails(strat.strategy_id);
                        }}
                        aria-label={isExpanded ? 'Collapse details' : 'Expand details'}
                      >
                        {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      </button>
                    </td>
                  </tr>

                  {/* Expanded Details */}
                  {isExpanded && (
                    <tr className="strategy-expanded-row">
                      <td colSpan={8}>
                        <div className="strategy-deep-details">
                          <div className="deep-details-grid">
                            <div>
                              <strong className="text-secondary text-xs">Can it be undone?</strong>
                              <div>
                                <span className={`badge ${getReversibilityBadgeClass(strat.reversibility)}`}>
                                  {getReversibilityLabel(strat.reversibility)}
                                </span>
                              </div>
                            </div>
                            <div className="col-span-2">
                              <strong className="text-secondary text-xs">Risks &amp; considerations:</strong>
                              <div className="text-sm text-slate-300">{strat.risk_notes}</div>
                            </div>
                          </div>

                          {strat.suggested_command && (
                            <div className="strat-cmd-box font-mono">
                              <div className="cmd-header">
                                <Terminal size={12} /> Command to run (requires operator approval):
                              </div>
                              <div className="cmd-row">
                                <code>{strat.suggested_command}</code>
                                <button
                                  className="cmd-copy-btn"
                                  onClick={(e) => handleCopy(strat.suggested_command!, e)}
                                  title="Copy command"
                                  aria-label="Copy suggested strategy command"
                                >
                                  {copiedCmd === strat.suggested_command ? (
                                    <Check size={12} className="text-emerald" />
                                  ) : (
                                    <Copy size={12} />
                                  )}
                                </button>
                              </div>
                            </div>
                          )}

                          {strat.preconditions && strat.preconditions.length > 0 && (
                            <div className="strat-preconditions-box">
                              <strong className="text-xs text-muted">Check these first:</strong>
                              <ul className="preconditions-list text-xs">
                                {strat.preconditions.map((p, pIdx) => (
                                  <li key={pIdx}>{p}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Mobile-Optimized Strategy Cards List (Phone Viewport) */}
      <div className="strategy-mobile-cards-list">
        {strategies.map((strat) => {
          const isWinner = strat.rank === 1;
          const isExpanded = expandedStrategyId === strat.strategy_id;

          return (
            <div
              key={`m-strat-${strat.strategy_id}`}
              className={`strategy-mobile-card ${isWinner ? 'strat-card-winner' : ''}`}
            >
              <div className="strat-mobile-top">
                <div className="strat-mobile-rank">
                  <span className={`rank-badge rank-${strat.rank <= 3 ? strat.rank : 'other'} font-mono`}>
                    {strat.rank === 1 ? <Trophy size={11} /> : `#${strat.rank}`}
                  </span>
                  {isWinner && <span className="winner-micro-tag">Best Option</span>}
                </div>
                <div className="strat-mobile-score font-mono">
                  <span className="text-muted text-xs">Score:</span>
                  <span className="font-bold text-emerald">{strat.final_score.toFixed(1)}/100</span>
                </div>
              </div>

              <h4 className="strat-mobile-title">{strat.name}</h4>
              <p className="strat-mobile-desc">{strat.description}</p>

              <div className="strat-mobile-metrics-grid font-mono">
                <div className="strat-mobile-metric">
                  <span className="metric-lbl">Impact (60%)</span>
                  <span className="metric-val text-amber">{strat.expected_impact.toFixed(0)}</span>
                </div>
                <div className="strat-mobile-metric">
                  <span className="metric-lbl">Safety (20%)</span>
                  <span className="metric-val text-emerald">{strat.safety.toFixed(0)}</span>
                </div>
                <div className="strat-mobile-metric">
                  <span className="metric-lbl">Speed (15%)</span>
                  <span className="metric-val text-cyan">{strat.speed.toFixed(0)}</span>
                </div>
                <div className="strat-mobile-metric">
                  <span className="metric-lbl">Cost (5%)</span>
                  <span className="metric-val text-indigo">{strat.affordability.toFixed(0)}</span>
                </div>
              </div>

              <div className="strat-mobile-actions">
                <button
                  className="btn-strat-mobile-expand"
                  onClick={() => toggleStrategyDetails(strat.strategy_id)}
                  aria-expanded={isExpanded}
                >
                  <span>{isExpanded ? 'Hide Details' : 'View Details & Command'}</span>
                  {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </button>
              </div>

              {isExpanded && (
                <div className="strat-mobile-expanded">
                  <div className="text-xs mb-2">
                    <span className="text-muted">Reversibility: </span>
                    <span className={`badge ${getReversibilityBadgeClass(strat.reversibility)}`}>
                      {getReversibilityLabel(strat.reversibility)}
                    </span>
                  </div>
                  <div className="text-xs text-muted mb-2">
                    <strong>Risks: </strong>{strat.risk_notes}
                  </div>

                  {strat.suggested_command && (
                    <div className="strat-cmd-box font-mono mt-2">
                      <div className="cmd-row">
                        <code className="text-xs">{strat.suggested_command}</code>
                        <button
                          className="cmd-copy-btn"
                          onClick={(e) => handleCopy(strat.suggested_command!, e)}
                          title="Copy command"
                          aria-label="Copy command"
                        >
                          {copiedCmd === strat.suggested_command ? (
                            <Check size={11} className="text-emerald" />
                          ) : (
                            <Copy size={11} />
                          )}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
