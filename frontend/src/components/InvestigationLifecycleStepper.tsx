import React, { useState, useEffect, useRef } from 'react';
import {
  Play,
  Pause,
  RotateCcw,
  SkipForward,
  ChevronRight,
  ChevronDown,
  Cpu,
  CheckCircle2,
  Clock,
} from 'lucide-react';
import type { InvestigationTraceItem } from '../types';

interface StepperProps {
  trace: InvestigationTraceItem[];
  replayIndex: number;
  isReplaying: boolean;
  onSetReplayIndex: (index: number) => void;
  onToggleReplay: () => void;
  onResetReplay: () => void;
  replaySpeed?: number;
  onSetReplaySpeed?: (speed: number) => void;
  runId: string;
  validationPassed: boolean;
}

/** Maps internal phase names to plain-English labels for non-technical readers. */
const phaseLabels: Record<string, string> = {
  COLLECTING: 'Gathering Data',
  RECONCILING: 'Cross-Checking',
  HYPOTHESIZING: 'Forming Theories',
  SCORING: 'Weighing Evidence',
  REPORTING: 'Building Report',
  VALIDATING: 'Quality Check',
  VALIDATED: 'Verified ✓',
  EXECUTION: 'Starting',
};

const getPhaseInfo = (item: InvestigationTraceItem) => {
  const summaryLower = item.summary.toLowerCase();
  const actionLower = item.action_type.toLowerCase();
  const toolLower = (item.tool_name || '').toLowerCase();
  const details = item.details || {};
  const toState = (details.to_state as string) || (details.state as string) || '';

  if (toState === 'VALIDATED' || summaryLower.includes('passed all strict validation') || actionLower === 'validation') {
    return { name: 'VALIDATED', colorClass: 'phase-validated', dotColor: '#10b981' };
  }
  if (toState === 'VALIDATING' || summaryLower.includes('validating') || toolLower.includes('validate')) {
    return { name: 'VALIDATING', colorClass: 'phase-validating', dotColor: '#38bdf8' };
  }
  if (toState === 'REPORTING' || actionLower === 'strategy_ranking' || summaryLower.includes('synthesizing repair') || summaryLower.includes('ranked')) {
    return { name: 'REPORTING', colorClass: 'phase-reporting', dotColor: '#38bdf8' };
  }
  if (toState === 'SCORING' || actionLower === 'deterministic_scoring' || summaryLower.includes('scoring') || summaryLower.includes('leading root cause')) {
    return { name: 'SCORING', colorClass: 'phase-scoring', dotColor: '#38bdf8' };
  }
  if (toState === 'HYPOTHESIZING' || toolLower.includes('hypothes') || summaryLower.includes('hypothes')) {
    return { name: 'HYPOTHESIZING', colorClass: 'phase-hypothesizing', dotColor: '#06b6d4' };
  }
  if (toState === 'RECONCILING' || toolLower.includes('reconcil') || summaryLower.includes('contradiction') || summaryLower.includes('tension')) {
    return { name: 'RECONCILING', colorClass: 'phase-reconciling', dotColor: '#f59e0b' };
  }
  if (toState === 'COLLECTING' || toolLower.includes('telemetry') || toolLower.includes('probe') || toolLower.includes('query') || actionLower === 'tool_result' || actionLower === 'tool_call') {
    return { name: 'COLLECTING', colorClass: 'phase-collecting', dotColor: '#06b6d4' };
  }
  return { name: 'EXECUTION', colorClass: 'phase-neutral', dotColor: '#94a3b8' };
};

export const InvestigationLifecycleStepper: React.FC<StepperProps> = ({
  trace,
  replayIndex,
  isReplaying,
  onSetReplayIndex,
  onToggleReplay,
  onResetReplay,
  replaySpeed = 1,
  onSetReplaySpeed,
  runId,
  validationPassed,
}) => {
  const [expandedTraceIdxs, setExpandedTraceIdxs] = useState<Record<number, boolean>>({});
  const activeNodeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isReplaying && activeNodeRef.current) {
      activeNodeRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [replayIndex, isReplaying]);

  const toggleDetails = (idx: number) => {
    setExpandedTraceIdxs((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const visibleTrace = trace.slice(0, Math.max(1, replayIndex));
  const isEnd = replayIndex >= trace.length;

  const handleStepForward = () => {
    if (replayIndex < trace.length) {
      onSetReplayIndex(replayIndex + 1);
    }
  };

  const handleStepBackward = () => {
    if (replayIndex > 1) {
      onSetReplayIndex(replayIndex - 1);
    }
  };

  const handleJumpToEnd = () => {
    onSetReplayIndex(trace.length);
  };

  return (
    <div className="card investigation-card">
      {/* Header */}
      <div className="card-header">
        <div className="card-title">
          <div className="title-icon-box">
            <Cpu size={16} />
          </div>
          <div>
            <span className="title-text">How the Investigation Unfolded</span>
            <span className="title-subtext">
              (Step {visibleTrace.length} of {trace.length})
            </span>
          </div>
        </div>

        <div className="trace-badges-group">
          {validationPassed ? (
            <span className="badge badge-healthy">
              <CheckCircle2 size={12} /> Results Verified
            </span>
          ) : (
            <span className="badge badge-failed">Verification Pending</span>
          )}
          <span className="badge badge-neutral font-mono">Report: {runId}</span>
        </div>
      </div>

      {/* Playback Controls */}
      <div className="timeline-controls-bar">
        <div className="controls-button-group">
          <button
            className="ctrl-btn"
            onClick={onResetReplay}
            disabled={replayIndex <= 1 && !isReplaying}
            title="Go back to the beginning"
          >
            <RotateCcw size={13} />
            <span>Start Over</span>
          </button>

          <button
            className="ctrl-btn ctrl-btn-primary"
            onClick={onToggleReplay}
            title={isReplaying ? 'Pause playback' : 'Watch it step by step'}
          >
            {isReplaying ? <Pause size={13} /> : <Play size={13} fill="currentColor" />}
            <span>{isReplaying ? 'Pause' : isEnd ? 'Replay' : 'Play'}</span>
          </button>

          <button
            className="ctrl-btn"
            onClick={handleStepBackward}
            disabled={replayIndex <= 1 || isReplaying}
            title="Previous step"
          >
            <span>Prev</span>
          </button>

          <button
            className="ctrl-btn"
            onClick={handleStepForward}
            disabled={replayIndex >= trace.length || isReplaying}
            title="Next step"
          >
            <span>Next</span>
          </button>

          <button
            className="ctrl-btn"
            onClick={handleJumpToEnd}
            disabled={replayIndex >= trace.length || isReplaying}
            title="Skip to the final results"
          >
            <SkipForward size={13} />
            <span>End</span>
          </button>

          {onSetReplaySpeed && (
            <div className="speed-toggle-group" style={{ display: 'inline-flex', gap: '2px', marginLeft: '0.5rem', background: 'rgba(15, 23, 42, 0.6)', borderRadius: '6px', padding: '2px', border: '1px solid rgba(51, 65, 85, 0.5)' }}>
              {[0.5, 1, 2].map((spd) => (
                <button
                  key={spd}
                  type="button"
                  onClick={() => onSetReplaySpeed(spd)}
                  className={`ctrl-btn ${replaySpeed === spd ? 'ctrl-btn-primary' : ''}`}
                  style={{ padding: '2px 8px', fontSize: '0.75rem', height: '24px', minWidth: '32px' }}
                  title={`Play at ${spd}x speed`}
                >
                  {spd}x
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Progress bar */}
        <div className="timeline-progress-wrap">
          <div className="timeline-progress-info font-mono">
            <span>Progress: {Math.round((replayIndex / (trace.length || 1)) * 100)}%</span>
            <span>Step {Math.min(replayIndex, trace.length)} of {trace.length}</span>
          </div>
          <div
            className="timeline-progress-bar-bg"
            role="slider"
            tabIndex={0}
            aria-label="Investigation step scrubber"
            aria-valuemin={1}
            aria-valuemax={trace.length}
            aria-valuenow={Math.min(replayIndex, trace.length)}
            aria-valuetext={`Step ${Math.min(replayIndex, trace.length)} of ${trace.length}`}
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const clickPos = (e.clientX - rect.left) / rect.width;
              const targetIdx = Math.max(1, Math.min(trace.length, Math.ceil(clickPos * trace.length)));
              onSetReplayIndex(targetIdx);
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
                e.preventDefault();
                onSetReplayIndex(Math.min(trace.length, replayIndex + 1));
              } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
                e.preventDefault();
                onSetReplayIndex(Math.max(1, replayIndex - 1));
              } else if (e.key === 'Home') {
                e.preventDefault();
                onSetReplayIndex(1);
              } else if (e.key === 'End') {
                e.preventDefault();
                onSetReplayIndex(trace.length);
              }
            }}
          >
            <div
              className="timeline-progress-bar-fill"
              style={{ width: `${(replayIndex / (trace.length || 1)) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Step-by-Step Timeline */}
      <div className="timeline-items-flow">
        {visibleTrace.map((item, idx) => {
          const phase = getPhaseInfo(item);
          const isExpanded = !!expandedTraceIdxs[idx];
          const hasDetails = item.details && Object.keys(item.details).length > 0;
          const recordsReturned = item.details?.records_returned as number | undefined;
          const recordsAppended = item.details?.records_appended as number | undefined;
          const recordsDeduped = item.details?.records_deduplicated as number | undefined;
          const friendlyPhase = phaseLabels[phase.name] || phase.name;
          const isActive = idx === replayIndex - 1;

          return (
            <div
              key={idx}
              ref={isActive ? activeNodeRef : null}
              className={`trace-node ${isActive ? 'trace-node-active' : ''}`}
            >
              <div className="trace-node-indicator">
                <div className="trace-node-dot" style={{ borderColor: phase.dotColor }} />
                {idx < visibleTrace.length - 1 && <div className="trace-node-line" />}
              </div>

              <div className="trace-node-content">
                <div className="trace-node-top">
                  <div className="trace-node-tags">
                    <span className="trace-round-badge font-mono">#{item.round_index}</span>
                    <span className={`phase-badge ${phase.colorClass}`}>{friendlyPhase}</span>
                  </div>

                  <div className="trace-timestamp font-mono">
                    <Clock size={11} /> {new Date(item.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </div>
                </div>

                <div className="trace-summary-row">
                  <div className="trace-summary-text">{item.summary}</div>
                </div>

                {/* Data metrics (shown in friendlier language) */}
                {(recordsReturned !== undefined || recordsAppended !== undefined || recordsDeduped !== undefined) && (
                  <div className="trace-metrics-chips">
                    {recordsReturned !== undefined && (
                      <span className="metric-chip">
                        <span className="chip-label">Found:</span>
                        <span className="chip-val font-mono">{recordsReturned}</span>
                      </span>
                    )}
                    {recordsAppended !== undefined && (
                      <span className="metric-chip">
                        <span className="chip-label">Added:</span>
                        <span className="chip-val font-mono">{recordsAppended}</span>
                      </span>
                    )}
                    {recordsDeduped !== undefined && (
                      <span className="metric-chip">
                        <span className="chip-label">Duplicates removed:</span>
                        <span className="chip-val font-mono">{recordsDeduped}</span>
                      </span>
                    )}
                  </div>
                )}

                {/* Technical details (collapsed by default) */}
                {hasDetails && (
                  <div className="trace-details-drawer">
                    <button
                      className="trace-expand-btn font-mono"
                      onClick={() => toggleDetails(idx)}
                    >
                      {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      <span>{isExpanded ? 'Hide technical details' : 'Show technical details'}</span>
                    </button>

                    {isExpanded && (
                      <pre className="trace-json-box font-mono">
                        {JSON.stringify(item.details, null, 2)}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
