import React from 'react';
import {
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  Flame,
  Zap,
} from 'lucide-react';
import type { Conflict, EvidenceObservation } from '../types';
import { ComponentBadge } from './ComponentBadge';

interface ScopeTensionsPanelProps {
  conflicts: Conflict[];
  evidenceList: EvidenceObservation[];
  onSelectEvidence?: (evidenceId: string) => void;
}

/** Maps internal conflict type codes to human-readable labels. */
const conflictTypeLabel = (ct: string): string => {
  switch (ct) {
    case 'DIRECT_CONTRADICTION': return 'Contradicting Signals';
    case 'SCOPE_TENSION': return 'Mixed Signals';
    case 'TEMPORAL_CONFLICT': return 'Timing Mismatch';
    default: return ct.replace(/_/g, ' ').toLowerCase();
  }
};

/** Calculates divergence ratio if values are numeric and positive. */
const calculateDivergence = (val1: number, val2: number): string | null => {
  if (typeof val1 === 'number' && typeof val2 === 'number' && val1 > 0 && val2 > 0) {
    const ratio = Math.max(val1, val2) / Math.min(val1, val2);
    if (ratio >= 2) {
      return `${ratio >= 10 ? Math.round(ratio).toLocaleString() : ratio.toFixed(1)}x Divergence`;
    }
  }
  return null;
};

export const ScopeTensionsPanel: React.FC<ScopeTensionsPanelProps> = ({
  conflicts,
  evidenceList,
  onSelectEvidence,
}) => {
  return (
    <div className="card tension-card">
      <div className="card-header">
        <div className="card-title">
          <div className="title-icon-box text-amber">
            <ShieldAlert size={16} />
          </div>
          <div>
            <span className="title-text">Conflicting Signals Found</span>
            <span className="title-subtext">
              ({conflicts.length} {conflicts.length === 1 ? 'conflict' : 'conflicts'} identified and explained)
            </span>
          </div>
        </div>
      </div>

      <div className="conflicts-container">
        {conflicts.length === 0 ? (
          <div className="empty-state">
            <CheckCircle2 size={24} className="text-emerald" />
            <p>All diagnostic signals agree: no contradictions found.</p>
          </div>
        ) : (
          conflicts.map((conflict) => {
            const linkedEvidence = evidenceList.filter((e) =>
              conflict.evidence_ids.includes(e.id)
            );
            const workloadEv = linkedEvidence.find((e) => e.scope === 'workload');
            const probeEv = linkedEvidence.find(
              (e) => e.scope === 'synthetic_probe' || e.source_group === 'health_probe'
            );

            const divergenceRatio = workloadEv && probeEv
              ? calculateDivergence(workloadEv.value, probeEv.value)
              : null;

            return (
              <div key={conflict.id} className="conflict-card-item">
                <div className="conflict-top-bar">
                  <div className="conflict-type-row">
                    <span className="conflict-type-pill">
                      {conflictTypeLabel(conflict.conflict_type)}
                    </span>
                    <ComponentBadge component={conflict.component} size="sm" />
                  </div>

                  <div className="conflict-ev-chips">
                    <span className="ev-label">Related data:</span>
                    {conflict.evidence_ids.map((id) => (
                      <button
                        key={id}
                        className="ev-id-chip font-mono"
                        onClick={() => onSelectEvidence?.(id)}
                        title={`Jump to evidence ${id}`}
                      >
                        {id}
                      </button>
                    ))}
                  </div>
                </div>

                <h3 className="conflict-headline">{conflict.headline}</h3>
                <p className="conflict-desc">{conflict.description}</p>

                {/* Side-by-side comparison: what production sees vs what a direct test shows */}
                {workloadEv && probeEv && (
                  <div className="juxtaposition-grid">
                    <div className="juxta-card juxta-workload">
                      <div className="juxta-badge">
                        <AlertTriangle size={11} /> What production traffic shows
                      </div>
                      <div className="juxta-signal font-mono">{workloadEv.signal}</div>
                      <div className="juxta-val font-mono">
                        {workloadEv.value} {workloadEv.unit}
                      </div>
                      <div className="juxta-detail">{workloadEv.details}</div>
                    </div>

                    <div className="juxta-vs-column">
                      <div className="juxta-vs">VS</div>
                      {divergenceRatio && (
                        <div className="divergence-pill font-mono">
                          <Zap size={10} /> {divergenceRatio}
                        </div>
                      )}
                    </div>

                    <div className="juxta-card juxta-probe">
                      <div className="juxta-badge">
                        <CheckCircle2 size={11} /> What a direct test shows
                      </div>
                      <div className="juxta-signal font-mono">{probeEv.signal}</div>
                      <div className="juxta-val font-mono">
                        {probeEv.value} {probeEv.unit}
                      </div>
                      <div className="juxta-detail">{probeEv.details}</div>
                    </div>
                  </div>
                )}

                {/* What this means for operations */}
                <div className="operational-insight-box">
                  <div className="insight-header">
                    <Flame size={13} className="text-amber" />
                    <span className="insight-title">What this means</span>
                  </div>
                  <div className="insight-text">{conflict.operational_implication}</div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
