import React, { useState } from 'react';
import {
  Play,
  RotateCcw,
  Copy,
  Download,
  Check,
  Layers,
} from 'lucide-react';
import type { ScenarioMetadata, AnalysisResult, HealthResponse } from '../types';
import { ComponentBadge } from './ComponentBadge';

interface ScenarioBarProps {
  scenarios: ScenarioMetadata[];
  selectedScenarioId: string;
  onScenarioChange: (id: string) => void;
  onRunInvestigation: () => void;
  onStartReplay: () => void;
  loading: boolean;
  isReplaying: boolean;
  health: HealthResponse | null;
  result: AnalysisResult | null;
}

export const ScenarioBar: React.FC<ScenarioBarProps> = ({
  scenarios,
  selectedScenarioId,
  onScenarioChange,
  onRunInvestigation,
  onStartReplay,
  loading,
  isReplaying,
  health,
  result,
}) => {
  const [copied, setCopied] = useState<boolean>(false);

  const selectedScenario = scenarios.find((s) => s.id === selectedScenarioId);

  const handleCopyJson = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy report JSON:', err);
    }
  };

  const handleDownloadJson = () => {
    if (!result) return;
    try {
      const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `faultline-report-${result.run_id || 'diagnostic'}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to download report JSON:', err);
    }
  };

  return (
    <section className="scenario-section">
      {/* Top Action Control Row */}
      <div className="action-bar-container">
        <div className="scenario-selector-wrap">
          <label htmlFor="scenario-select" className="scenario-label">
            <Layers size={14} className="text-muted" /> Choose an incident to investigate:
          </label>
          <select
            id="scenario-select"
            className="scenario-select"
            value={selectedScenarioId}
            onChange={(e) => onScenarioChange(e.target.value)}
            disabled={loading}
            aria-label="Choose an incident scenario to investigate"
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </div>

        <div className="action-buttons-wrap">
          <button
            className="btn-primary"
            onClick={onRunInvestigation}
            disabled={loading || (health !== null && health.analysis_ready === false)}
            title="Start a full diagnostic investigation of this incident"
          >
            {loading ? (
              <>
                <span className="spinner" />
                <span>Investigating...</span>
              </>
            ) : (
              <>
                <Play size={14} fill="currentColor" />
                <span>Diagnose This Incident</span>
              </>
            )}
          </button>

          {result && (
            <>
              <button
                className="btn-secondary"
                onClick={onStartReplay}
                disabled={isReplaying || loading}
                title="Watch the investigation unfold step by step"
              >
                <RotateCcw size={14} />
                <span>Watch Replay</span>
              </button>

              <button
                className="btn-secondary"
                onClick={handleCopyJson}
                title="Copy the full diagnostic report as JSON"
              >
                {copied ? <Check size={14} className="text-emerald" /> : <Copy size={14} />}
                <span>{copied ? 'Copied JSON!' : 'Copy JSON'}</span>
              </button>

              <button
                className="btn-secondary btn-icon-only"
                onClick={handleDownloadJson}
                title="Download the full diagnostic report as a JSON file"
                aria-label="Download JSON Report"
              >
                <Download size={14} />
                <span className="btn-text-responsive">Download JSON</span>
              </button>
            </>
          )}
        </div>
      </div>

      {/* Scenario Context Card (Compact & Clean) */}
      {selectedScenario && (
        <div className={`scenario-context-card ${result ? 'context-card-compact' : ''}`}>
          <div className="context-header">
            <div className="context-title-wrap">
              <span className="context-indicator-bar" />
              <div>
                <h2 className="context-title">{selectedScenario.title}</h2>
                <div className="context-id font-mono">Scenario: {selectedScenario.id}</div>
              </div>
            </div>
            <div className="context-components">
              <span className="comp-label">Impacted Services:</span>
              <div className="comp-badges-list">
                {selectedScenario.affected_components.map((comp) => (
                  <ComponentBadge key={comp} component={comp} size="sm" />
                ))}
              </div>
            </div>
          </div>
          {!result && <p className="context-description">{selectedScenario.description}</p>}
        </div>
      )}
    </section>
  );
};
