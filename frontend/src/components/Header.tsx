import React from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ShieldAlert,
  Terminal,
} from 'lucide-react';
import type { HealthResponse, AnalysisResult } from '../types';

interface HeaderProps {
  health: HealthResponse | null;
  result: AnalysisResult | null;
}

export const Header: React.FC<HeaderProps> = ({ health }) => {
  const isOffline =
    health?.provider_mode === 'deterministic_fake' ||
    health?.runtime_model?.includes('offline-deterministic-fake');

  return (
    <header className="app-header">
      <div className="brand-area">
        <div className="brand-logo-container">
          <div className="brand-logo">
            <Activity size={18} className="brand-logo-icon" />
          </div>
          <div className="brand-pulse-ring" />
        </div>
        <div>
          <div className="brand-title-row">
            <h1 className="brand-title">Faultline</h1>
            <span className="version-pill">v{health?.version || '0.1.0'}</span>
          </div>
          <div className="brand-subtitle">AI-Powered Incident Diagnosis &amp; Repair Advisor</div>
        </div>
      </div>

      <div className="header-meta">
        {isOffline && (
          <div className="meta-pill font-mono text-xs text-muted" title="Running in deterministic offline demonstration mode">
            <Terminal size={12} className="meta-icon" />
            <span>Offline Demo</span>
          </div>
        )}

        {/* Analysis Readiness Badge */}
        {!health ? (
          <div className="meta-pill badge-neutral">
            <span className="status-dot dot-neutral dot-pulse" />
            <AlertTriangle size={12} />
            <span>Connecting...</span>
          </div>
        ) : health.analysis_ready === false || health.status !== 'healthy' ? (
          <div className="meta-pill badge-failed">
            <span className="status-dot dot-failed" />
            <ShieldAlert size={12} />
            <span>Not Ready</span>
          </div>
        ) : (
          <div className="meta-pill badge-healthy">
            <span className="status-dot dot-healthy dot-pulse" />
            <CheckCircle2 size={12} />
            <span>Ready</span>
          </div>
        )}
      </div>
    </header>
  );
};
