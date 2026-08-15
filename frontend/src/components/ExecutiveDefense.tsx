import React from 'react';
import {
  FileText,
  Scale,
  Sparkles,
} from 'lucide-react';
import type { DecisionExplanation } from '../types';

interface ExecutiveDefenseProps {
  recommendation: DecisionExplanation;
  onSelectEvidence?: (evidenceId: string) => void;
}

export const ExecutiveDefense: React.FC<ExecutiveDefenseProps> = ({
  recommendation,
  onSelectEvidence,
}) => {
  const grounding = recommendation.grounding;

  return (
    <section className="card defense-simple-card" aria-label="Investigation Rationale">
      <div className="defense-simple-header">
        <div className="title-icon-box text-cyan">
          <FileText size={16} />
        </div>
        <div>
          <h3 className="defense-simple-title">Why This Fix Was Selected</h3>
          <p className="defense-simple-subtitle">
            Summary of reasoning and evidence comparison
          </p>
        </div>
      </div>

      <div className="defense-simple-body">
        {/* Core Summary */}
        <p className="defense-main-text">{recommendation.executive_summary}</p>

        {/* 2-Column Trade-Off & Conflict Breakdown */}
        <div className="defense-insights-grid">
          <div className="defense-insight-box">
            <div className="insight-box-title text-emerald">
              <Scale size={13} />
              <span>Why Other Fixes Were Not Recommended</span>
            </div>
            <p className="insight-box-text">
              {recommendation.trade_off_comparison.rejection_rationale}
            </p>
          </div>

          <div className="defense-insight-box">
            <div className="insight-box-title text-cyan">
              <Sparkles size={13} />
              <span>Resolving Conflicting Signals</span>
            </div>
            <p className="insight-box-text">
              {recommendation.grounded_contradiction_analysis}
            </p>
            {grounding && grounding.reconciled_evidence_ids?.length > 0 && (
              <div className="insight-evidence-row font-mono text-xs">
                <span className="text-muted">Supporting evidence:</span>
                {grounding.reconciled_evidence_ids.map((eid) => (
                  <button
                    key={eid}
                    className="ev-id-chip"
                    onClick={() => onSelectEvidence?.(eid)}
                    title={`View evidence ${eid}`}
                  >
                    {eid}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
};
