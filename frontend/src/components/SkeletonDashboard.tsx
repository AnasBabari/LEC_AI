import React from 'react';
import { Cpu } from 'lucide-react';

export const SkeletonDashboard: React.FC = () => {
  return (
    <div
      className="skeleton-dashboard-container"
      aria-busy="true"
      aria-label="Investigating incident and generating diagnosis..."
    >
      {/* Loading Progress Bar */}
      <div className="skeleton-status-banner">
        <div className="skeleton-status-top">
          <div className="skeleton-pulse-icon">
            <Cpu size={16} className="text-cyan animate-pulse" />
          </div>
          <div className="skeleton-status-text">
            <div className="skeleton-status-title">Diagnosing Incident in Real-Time...</div>
            <div className="skeleton-status-subtitle">
              Querying telemetry metrics, executing synthetic probes, evaluating root-cause theories, and scoring repair actions.
            </div>
          </div>
        </div>

        <div className="skeleton-phases-strip">
          <span className="phase-pill phase-collecting">1. Gathering Data</span>
          <span className="phase-pill phase-reconciling">2. Cross-Checking</span>
          <span className="phase-pill phase-hypothesizing">3. Forming Theories</span>
          <span className="phase-pill phase-scoring">4. Weighing Evidence</span>
          <span className="phase-pill phase-validating">5. Quality Check</span>
        </div>
      </div>

      {/* Hero Banner Shimmer (Matches Incident Hero Layout) */}
      <div className="skeleton-card skeleton-hero">
        <div className="skeleton-line skeleton-w-30" />
        <div className="skeleton-grid-2">
          <div className="skeleton-box skeleton-h-140" />
          <div className="skeleton-box skeleton-h-140" />
        </div>
      </div>

      {/* Executive Defense Shimmer */}
      <div className="skeleton-card skeleton-h-160">
        <div className="skeleton-line skeleton-w-40" />
        <div className="skeleton-line skeleton-w-80" />
        <div className="skeleton-line skeleton-w-60" />
      </div>

      {/* Safety Console Shimmer */}
      <div className="skeleton-card skeleton-h-100">
        <div className="skeleton-line skeleton-w-50" />
        <div className="skeleton-line skeleton-w-70" />
      </div>
    </div>
  );
};
