import React, { useState } from 'react';
import {
  Database,
  Search,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import type { EvidenceObservation, Conflict } from '../types';
import { ComponentBadge } from './ComponentBadge';
import { StatusBadge } from './StatusBadge';

interface EvidenceLedgerProps {
  evidence: EvidenceObservation[];
  conflicts?: Conflict[];
  selectedEvidenceId?: string | null;
  onClearSelectedEvidence?: () => void;
}

/** Maps source group codes to human-readable labels. */
const sourceGroupLabel = (sg: string): string => {
  switch (sg) {
    case 'telemetry': return 'Live Monitoring';
    case 'health_probe': return 'Direct Test';
    case 'operational_events': return 'System Events';
    default: return sg.replace(/_/g, ' ');
  }
};

/** Maps scope codes to human-readable labels. */
const scopeLabel = (s: string): string => {
  switch (s) {
    case 'workload': return 'Production';
    case 'synthetic_probe': return 'Test Probe';
    default: return s.replace(/_/g, ' ');
  }
};

/** Maps reliability codes to human-readable labels. */
const reliabilityLabel = (r: string): string => {
  switch (r) {
    case 'verified': return 'Verified';
    case 'aggregated': return 'Aggregated';
    case 'advisory': return 'Advisory';
    default: return r;
  }
};

/** Maps dimension codes to friendlier names. */
const dimensionLabel = (d: string): string => {
  switch (d) {
    case 'latency': return 'Response Time';
    case 'availability': return 'Availability';
    case 'freshness': return 'Data Freshness';
    case 'throughput': return 'Throughput';
    case 'backlog': return 'Queue Backlog';
    case 'query_efficiency': return 'Query Speed';
    default: return d.replace(/_/g, ' ');
  }
};

export const EvidenceLedger: React.FC<EvidenceLedgerProps> = ({
  evidence,
  selectedEvidenceId,
  onClearSelectedEvidence,
}) => {
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [componentFilter, setComponentFilter] = useState<string>('all');
  const [sourceFilter, setSourceFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});

  const handleCopyId = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const toggleRowExpand = (id: string) => {
    setExpandedRows((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const filteredEvidence = evidence.filter((obs) => {
    if (componentFilter !== 'all' && obs.component !== componentFilter) return false;
    if (sourceFilter !== 'all' && obs.source_group !== sourceFilter) return false;
    if (statusFilter !== 'all' && obs.status !== statusFilter) return false;

    if (searchTerm.trim()) {
      const q = searchTerm.toLowerCase();
      const matchId = obs.id.toLowerCase().includes(q);
      const matchSignal = obs.signal.toLowerCase().includes(q);
      const matchSource = obs.source.toLowerCase().includes(q);
      const matchDetails = obs.details.toLowerCase().includes(q);
      const matchComp = obs.component.toLowerCase().includes(q);
      if (!matchId && !matchSignal && !matchSource && !matchDetails && !matchComp) {
        return false;
      }
    }
    return true;
  });

  return (
    <div className="card evidence-main-card">
      <div className="card-header">
        <div className="card-title">
          <div className="title-icon-box text-emerald">
            <Database size={16} />
          </div>
          <div>
            <span className="title-text">All Collected Evidence</span>
            <span className="title-subtext font-mono" role="status" aria-live="polite">
              ({filteredEvidence.length} of {evidence.length} data points)
            </span>
          </div>
        </div>

        {/* Selected Evidence Clear Bar */}
        {selectedEvidenceId && (
          <div className="selected-evidence-banner">
            <span>Filtered by highlighted evidence: <strong>{selectedEvidenceId}</strong></span>
            <button className="btn-clear-highlight" onClick={onClearSelectedEvidence}>
              Show All
            </button>
          </div>
        )}

        {/* Search & Filter Controls */}
        <div className="evidence-filter-bar">
          <div className="search-input-wrap">
            <Search size={13} className="search-icon text-muted" />
            <input
              type="text"
              className="search-input"
              placeholder="Search evidence..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              aria-label="Search evidence by ID, signal, or details"
            />
            {searchTerm && (
              <button
                className="search-clear-btn"
                onClick={() => setSearchTerm('')}
                aria-label="Clear search input"
              >
                ×
              </button>
            )}
          </div>

          <select
            className="filter-select"
            value={componentFilter}
            onChange={(e) => setComponentFilter(e.target.value)}
            aria-label="Filter evidence by affected system"
          >
            <option value="all">All Systems</option>
            <option value="api_gateway">API Gateway</option>
            <option value="database">Database</option>
            <option value="cache">Cache</option>
            <option value="message_queue">Message Queue</option>
          </select>

          <select
            className="filter-select"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            aria-label="Filter evidence by data source"
          >
            <option value="all">All Data Sources</option>
            <option value="telemetry">Live Monitoring</option>
            <option value="health_probe">Direct Tests</option>
            <option value="operational_events">System Events</option>
          </select>

          <select
            className="filter-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            aria-label="Filter evidence by status"
          >
            <option value="all">All Statuses</option>
            <option value="healthy">Healthy</option>
            <option value="degraded">Degraded</option>
            <option value="failed">Failed</option>
          </select>
        </div>
      </div>

      {/* Desktop/Tablet Evidence Table */}
      <div className="ledger-table-wrap table-responsive-wrapper">
        <table className="data-table evidence-table">
          <thead>
            <tr>
              <th style={{ width: '100px' }}>ID</th>
              <th style={{ width: '130px' }}>Data Source</th>
              <th style={{ width: '140px' }}>System</th>
              <th>What Was Measured</th>
              <th style={{ width: '110px' }}>Status</th>
              <th style={{ width: '130px' }}>Reading</th>
              <th style={{ width: '110px' }}>Context</th>
              <th style={{ width: '100px' }}>Trust Level</th>
              <th style={{ width: '50px' }}></th>
            </tr>
          </thead>
          <tbody>
            {filteredEvidence.length === 0 ? (
              <tr>
                <td colSpan={9} className="text-center py-6 text-muted">
                  No evidence matches your current filters.
                </td>
              </tr>
            ) : (
              filteredEvidence.map((obs) => {
                const isSelected = selectedEvidenceId === obs.id;
                const isExpanded = !!expandedRows[obs.id];

                return (
                  <React.Fragment key={obs.id}>
                    <tr
                      className={`evidence-row ${isSelected ? 'row-highlighted' : ''}`}
                      onClick={() => toggleRowExpand(obs.id)}
                    >
                      <td>
                        <div className="evidence-id-cell">
                          <span className="badge badge-neutral font-mono">{obs.id}</span>
                          <button
                            className="id-copy-btn"
                            onClick={(e) => handleCopyId(obs.id, e)}
                            title={`Copy evidence ID ${obs.id}`}
                            aria-label={`Copy evidence ID ${obs.id}`}
                          >
                            {copiedId === obs.id ? (
                              <Check size={11} className="text-emerald" />
                            ) : (
                              <Copy size={11} />
                            )}
                          </button>
                        </div>
                      </td>
                      <td>
                        <span className="source-group-tag">{sourceGroupLabel(obs.source_group)}</span>
                      </td>
                      <td>
                        <ComponentBadge component={obs.component} size="sm" />
                      </td>
                      <td>
                        <div className="signal-cell">
                          <span className="signal-name">{obs.signal}</span>
                          <span className="dimension-tag">{dimensionLabel(obs.dimension)}</span>
                        </div>
                      </td>
                      <td>
                        <StatusBadge status={obs.status} size="sm" />
                      </td>
                      <td>
                        <div className="metric-val-cell font-mono">
                          <span className="val-number">{obs.value}</span>
                          <span className="val-unit">{obs.unit}</span>
                        </div>
                      </td>
                      <td>
                        <span className={`scope-chip chip-${obs.scope}`}>
                          {scopeLabel(obs.scope)}
                        </span>
                      </td>
                      <td>
                        <span className={`reliability-chip rel-${obs.reliability}`}>
                          {reliabilityLabel(obs.reliability)}
                        </span>
                      </td>
                      <td>
                        <button
                          className="expand-arrow-btn"
                          aria-expanded={isExpanded}
                          aria-controls={`evidence-detail-${obs.id}`}
                          aria-label={isExpanded ? `Collapse details for ${obs.id}` : `Expand details for ${obs.id}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleRowExpand(obs.id);
                          }}
                        >
                          {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                        </button>
                      </td>
                    </tr>

                    {/* Expanded details */}
                    {isExpanded && (
                      <tr id={`evidence-detail-${obs.id}`} className="evidence-details-row">
                        <td colSpan={9}>
                          <div className="evidence-expanded-details">
                            <div className="details-header text-xs text-muted">
                              <span>Source: {obs.source}</span>
                              <span>Observed: {new Date(obs.observed_at).toLocaleString()}</span>
                              <span>Window: {new Date(obs.window_start).toLocaleTimeString()} to {new Date(obs.window_end).toLocaleTimeString()}</span>
                            </div>
                            <div className="details-body">
                              <strong>Details:</strong>
                              <p>{obs.details}</p>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Mobile-Optimized Evidence Priority Cards (Phone Viewport) */}
      <div className="evidence-mobile-cards-list">
        {filteredEvidence.map((obs) => {
          const isSelected = selectedEvidenceId === obs.id;
          const isExpanded = !!expandedRows[obs.id];

          return (
            <div
              key={`m-${obs.id}`}
              className={`evidence-mobile-card ${isSelected ? 'card-highlighted' : ''}`}
            >
              <div className="ev-card-top">
                <div className="ev-card-left">
                  <span className="badge badge-neutral font-mono">{obs.id}</span>
                  <ComponentBadge component={obs.component} size="sm" />
                </div>
                <div className="ev-card-right">
                  <StatusBadge status={obs.status} size="sm" />
                </div>
              </div>

              <div className="ev-card-signal-row">
                <div className="ev-card-signal-title">{obs.signal}</div>
                <div className="ev-card-metric font-mono">
                  {obs.value} {obs.unit}
                </div>
              </div>

              <div className="ev-card-tags-row">
                <span className="source-group-tag text-xs">{sourceGroupLabel(obs.source_group)}</span>
                <span className={`scope-chip chip-${obs.scope} text-xs`}>{scopeLabel(obs.scope)}</span>
                <span className={`reliability-chip rel-${obs.reliability} text-xs`}>{reliabilityLabel(obs.reliability)}</span>
              </div>

              <div className="ev-card-actions">
                <button
                  className="btn-ev-card-copy font-mono"
                  onClick={(e) => handleCopyId(obs.id, e)}
                  aria-label={`Copy ID ${obs.id}`}
                >
                  {copiedId === obs.id ? <Check size={11} className="text-emerald" /> : <Copy size={11} />}
                  <span>{copiedId === obs.id ? 'Copied' : 'Copy ID'}</span>
                </button>

                <button
                  className="btn-ev-card-expand"
                  onClick={() => toggleRowExpand(obs.id)}
                  aria-expanded={isExpanded}
                  aria-label={isExpanded ? `Hide details for ${obs.id}` : `Show details for ${obs.id}`}
                >
                  <span>{isExpanded ? 'Less Info' : 'More Info'}</span>
                  {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                </button>
              </div>

              {isExpanded && (
                <div className="ev-card-expanded-body">
                  <div className="text-xs text-muted">
                    <div>Source: {obs.source}</div>
                    <div>Observed: {new Date(obs.observed_at).toLocaleTimeString()}</div>
                  </div>
                  <p className="ev-card-details-text">{obs.details}</p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
