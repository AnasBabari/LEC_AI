import React from 'react';
import {
  Trophy,
  Cpu,
  ArrowRight,
  AlertCircle,
} from 'lucide-react';
import type { AnalysisResult } from '../types';
import { ExecutiveDefense } from './ExecutiveDefense';
import { SafetyConsole } from './SafetyConsole';

interface OverviewSummaryProps {
  result: AnalysisResult;
  onNavigateTab: (tab: 'causes' | 'repair' | 'timeline' | 'evidence') => void;
  onSelectEvidence?: (evidenceId: string) => void;
}

export const OverviewSummary: React.FC<OverviewSummaryProps> = ({
  result,
  onNavigateTab,
  onSelectEvidence,
}) => {
  const topHypothesis = result.hypotheses[0];
  const topStrategy = result.strategy_ranking.find((s) => s.rank === 1) || result.strategy_ranking[0];
  const conflictCount = result.conflicts.length;
  const evidenceCount = result.evidence.length;
  const severity = result.incident?.severity || 'critical';

  return (
    <div className="overview-flow">
      {/* 1. Incident Diagnostic Hero Banner (The Core Finding) */}
      <div className="incident-hero-banner">
        <div className="incident-hero-topline">
          <div className="hero-status-wrap">
            <span className="hero-status-badge font-mono">
              <span className="status-dot dot-healthy dot-pulse" />
              DIAGNOSIS COMPLETE
            </span>
            <span className={`badge font-mono ${severity === 'critical' ? 'badge-failed' : 'badge-degraded'}`}>
              <AlertCircle size={11} /> {severity.toUpperCase()} SEVERITY
            </span>
            <span className="hero-run-id font-mono">Run: {result.run_id}</span>
          </div>

          <div className="hero-metrics-pill font-mono">
            <span>{evidenceCount} observations</span>
            <span className="hero-dot-sep">•</span>
            <span>{result.hypotheses.length} possible causes</span>
            <span className="hero-dot-sep">•</span>
            <span>{conflictCount} signal conflicts analyzed</span>
          </div>
        </div>

        <div className="incident-hero-grid">
          {/* Left Column: Top Cause with Confidence */}
          <div
            className="hero-diagnostic-card"
            onClick={() => onNavigateTab('causes')}
            role="button"
            tabIndex={0}
            aria-label="View root cause analysis details"
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onNavigateTab('causes');
              }
            }}
          >
            <div className="hero-card-eyebrow text-cyan">
              <Cpu size={14} />
              <span>PRIMARY ROOT CAUSE ({topHypothesis ? `${topHypothesis.decision_weight.toFixed(0)}% Confidence` : 'Evaluated'})</span>
            </div>
            <h2 className="hero-card-headline">{topHypothesis?.name || result.recommendation.grounding?.top_cause_code || 'Detected Cause'}</h2>
            <p className="hero-card-summary">{topHypothesis?.summary || 'Primary root cause identified through systematic telemetry & log analysis.'}</p>
            <div className="hero-card-footer text-cyan font-mono">
              <span>View cause analysis &amp; evidence</span>
              <ArrowRight size={13} />
            </div>
          </div>

          {/* Right Column: #1 Recommended Fix with Score */}
          <div
            className="hero-repair-card"
            onClick={() => onNavigateTab('repair')}
            role="button"
            tabIndex={0}
            aria-label="Compare recommended repair actions"
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onNavigateTab('repair');
              }
            }}
          >
            <div className="hero-card-eyebrow text-emerald">
              <Trophy size={14} />
              <span>RECOMMENDED ACTION (Score: {topStrategy ? `${topStrategy.final_score.toFixed(1)}/100` : 'Top Ranked'})</span>
            </div>
            <h2 className="hero-card-headline">{topStrategy?.name || result.recommendation.grounding?.winning_strategy_name || 'Recommended Fix'}</h2>
            <p className="hero-card-summary">{topStrategy?.description || 'Optimal repair action balancing impact, safety, and speed.'}</p>
            <div className="hero-card-footer text-emerald font-mono">
              <span>Compare recovery options</span>
              <ArrowRight size={13} />
            </div>
          </div>
        </div>
      </div>

      {/* 2. Executive Rationale & Decision Defense */}
      <ExecutiveDefense
        recommendation={result.recommendation}
        onSelectEvidence={onSelectEvidence}
      />

      {/* 3. Safety Console (Suggested Command & Verification Checklist) */}
      <SafetyConsole execution={result.execution} />
    </div>
  );
};
