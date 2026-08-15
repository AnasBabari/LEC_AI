import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from './App';
import * as api from './api';
import type { AnalysisResult, HealthResponse, ScenarioMetadata } from './types';

const mockHealth: HealthResponse = {
  status: 'healthy',
  service: 'faultline',
  version: '0.1.0',
  gemini_configured: false,
  provider_mode: 'deterministic_fake',
  runtime_model: 'offline-deterministic-fake',
  fallback_model: undefined,
  discovered_accessible: true,
};

const mockScenarios: ScenarioMetadata[] = [
  {
    id: 'cache_invalidation_lag',
    title: 'Cache Invalidation Lag',
    description: 'Stalled queue consumer causing stale cache reads and DB exhaustion',
    affected_components: ['api_gateway', 'cache', 'database', 'message_queue'],
  },
  {
    id: 'index_regression',
    title: 'Database Index Regression',
    description: 'Missing index causing full table scans',
    affected_components: ['database'],
  },
];

const mockResult: AnalysisResult = {
  run_id: 'RUN-TEST-001',
  scenario_id: 'cache_invalidation_lag',
  state: 'VALIDATED',
  incident: {
    title: 'High Latency Alert',
    description: 'API latency spike',
    headline: 'High Latency Alert',
    severity: 'critical',
    reported_at: '2026-08-14T00:00:00Z',
    details: 'Details here',
    affected_components: ['cache', 'database'],
  },
  model_execution: {
    configured_primary_model: 'offline-deterministic-fake',
    configured_fallback_model: undefined,
    model_used: 'offline-deterministic-fake',
    thinking_level: 'none',
    fallback_occurred: false,
    fallback_reason: undefined,
    prompt_tokens: undefined,
    completion_tokens: undefined,
  },
  investigation_trace: [
    {
      round_index: 1,
      action_type: 'tool_call',
      timestamp: '2026-08-14T00:00:01Z',
      tool_name: 'query_telemetry',
      summary: 'Queried telemetry metrics',
      details: {},
    },
    {
      round_index: 2,
      action_type: 'validation',
      timestamp: '2026-08-14T00:00:05Z',
      tool_name: undefined,
      summary: 'Report passed all strict validation and safety checks.',
      details: { state: 'VALIDATED' },
    },
  ],
  evidence: [
    {
      id: 'EV-001',
      source_group: 'telemetry',
      source: 'Prometheus',
      component: 'database',
      signal: 'db_latency',
      dimension: 'latency',
      value: 2400,
      unit: 'ms',
      status: 'degraded',
      observed_at: '2026-08-14T00:00:00Z',
      window_start: '2026-08-14T00:00:00Z',
      window_end: '2026-08-14T00:00:00Z',
      scope: 'workload',
      reliability: 'aggregated',
      details: 'Workload latency spike',
    },
    {
      id: 'EV-002',
      source_group: 'health_probe',
      source: 'K8s',
      component: 'database',
      signal: 'db_ping',
      dimension: 'latency',
      value: 1.8,
      unit: 'ms',
      status: 'healthy',
      observed_at: '2026-08-14T00:00:00Z',
      window_start: '2026-08-14T00:00:00Z',
      window_end: '2026-08-14T00:00:00Z',
      scope: 'synthetic_probe',
      reliability: 'verified',
      details: 'Direct ping responsive',
    },
  ],
  conflicts: [
    {
      id: 'CONF-001',
      conflict_type: 'SCOPE_TENSION',
      component: 'database',
      evidence_ids: ['EV-001', 'EV-002'],
      headline: 'Scope Tension on database: Workload vs Synthetic Probe',
      description: 'Workload latency is degraded while synthetic ping is healthy.',
      operational_implication: 'Database is healthy but overwhelmed by external workload.',
    },
  ],
  hypotheses: [
    {
      cause_code: 'CACHE_INVALIDATION_CONSUMER_STALLED',
      name: 'Cache Invalidation Consumer Stalled',
      summary: 'Consumer worker crashed',
      causal_chain: ['Worker crashed', 'Queue accumulated', 'Cache went stale'],
      supporting_observations: [],
      opposing_observations: [],
      supporting_score: 14.0,
      opposing_score: 0.0,
      net_evidence_score: 14.0,
      decision_weight: 100.0,
      strength_band: 'STRONG',
      unresolved_uncertainties: [],
    },
  ],
  strategy_ranking: [
    {
      strategy_id: 'RECOVER_CONSUMER_AND_DRAIN',
      name: 'Restart Invalidation Consumer & Drain Backlog',
      description: 'Restart the consumer pool and drain queue',
      expected_impact: 73.7,
      safety: 75.0,
      speed: 50.0,
      affordability: 75.0,
      final_score: 70.5,
      rank: 1,
      risk_notes: 'Low risk transient broker load',
      reversibility: 'High',
      suggested_command: 'kubectl rollout restart deployment/cache-invalidation-worker',
      preconditions: ['Verify queue reachability'],
    },
    {
      strategy_id: 'RESTART_CACHE',
      name: 'Flush & Restart Cache Cluster',
      description: 'Flush cache nodes',
      expected_impact: 18.4,
      safety: 25.0,
      speed: 100.0,
      affordability: 100.0,
      final_score: 36.0,
      rank: 2,
      risk_notes: '100% cache stampede onto DB',
      reversibility: 'Irreversible',
      suggested_command: 'redis-cli flushall',
      preconditions: [],
    },
  ],
  recommendation: {
    executive_summary: "Recommended Action: 'Restart Invalidation Consumer & Drain Backlog'.",
    winning_strategy_id: 'RECOVER_CONSUMER_AND_DRAIN',
    trade_off_comparison: {
      alternative_strategy_id: 'RESTART_CACHE',
      alternative_strategy_name: 'Flush & Restart Cache Cluster',
      alternative_advantage: 'Higher speed (100/100).',
      rejection_rationale: 'Rejected due to cache stampede risk.',
    },
    grounded_contradiction_analysis: 'Reconciles CONF-001 by explaining cache miss cascade onto healthy database.',
    remaining_uncertainties: [],
  },
  execution: {
    execution_status: 'not_executed',
    operator_approval_required: true,
    suggested_command: 'kubectl rollout restart deployment/cache-invalidation-worker',
    safety_preconditions: ['Verify queue reachability'],
  },
  validation_passed: true,
};

describe('Faultline App Component', () => {
  beforeEach(() => {
    vi.spyOn(api, 'fetchHealth').mockResolvedValue(mockHealth);
    vi.spyOn(api, 'fetchScenarios').mockResolvedValue(mockScenarios);
    vi.spyOn(api, 'analyzeScenario').mockResolvedValue(mockResult);
  });

  it('renders initial dashboard header and scenario selector', async () => {
    render(<App />);

    expect(screen.getByRole('heading', { name: /Faultline/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByText(/Cache Invalidation Lag/i).length).toBeGreaterThan(0);
    });
  });

  it('displays truthful offline mode provenance badge', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByText(/Offline Demo/i).length).toBeGreaterThan(0);
    });
  });

  it('runs analysis and renders winning strategy at rank #1 with suggested command', async () => {
    render(<App />);

    const runBtn = screen.getByRole('button', { name: /Diagnose This Incident/i });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(screen.getAllByText(/Restart Invalidation Consumer & Drain Backlog/i).length).toBeGreaterThan(0);
      expect(screen.getByRole('tab', { name: /Repair Options/i })).toBeInTheDocument();
      expect(screen.getByText(/kubectl rollout restart deployment\/cache-invalidation-worker/i)).toBeInTheDocument();
    });
  });

  it('provides accessible Copy JSON and Download JSON buttons upon diagnosis', async () => {
    render(<App />);

    const runBtn = screen.getByRole('button', { name: /Diagnose This Incident/i });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Copy JSON/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Download JSON/i })).toBeInTheDocument();
    });
  });

  it('supports keyboard roving focus across dashboard tabs', async () => {
    render(<App />);

    const runBtn = screen.getByRole('button', { name: /Diagnose This Incident/i });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /Overview/i })).toBeInTheDocument();
    });

    const overviewTab = screen.getByRole('tab', { name: /Overview/i });
    expect(overviewTab).toHaveAttribute('aria-selected', 'true');
    expect(overviewTab).toHaveAttribute('tabindex', '0');

    // Press ArrowRight to move to Causes tab
    fireEvent.keyDown(overviewTab, { key: 'ArrowRight' });

    await waitFor(() => {
      const causesTab = screen.getByRole('tab', { name: /Root Causes/i });
      expect(causesTab).toHaveAttribute('aria-selected', 'true');
      expect(causesTab).toHaveAttribute('tabindex', '0');
      expect(overviewTab).toHaveAttribute('tabindex', '-1');
    });

    // Press End key to jump to Evidence tab
    const currentTab = screen.getByRole('tab', { name: /Root Causes/i });
    fireEvent.keyDown(currentTab, { key: 'End' });

    await waitFor(() => {
      const evidenceTab = screen.getByRole('tab', { name: /Evidence/i });
      expect(evidenceTab).toHaveAttribute('aria-selected', 'true');
    });
  });

  it('allows checking safety preconditions with accessible checkbox inputs', async () => {
    render(<App />);

    const runBtn = screen.getByRole('button', { name: /Diagnose This Incident/i });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(screen.getByText(/Before running this command, verify:/i)).toBeInTheDocument();
    });

    const checkbox = screen.getByRole('checkbox', { name: /Verify precondition: Verify queue reachability/i });
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(screen.getByText(/All listed preconditions marked as reviewed. Operator approval is still required./i)).toBeInTheDocument();
  });

  it('clears stale analysis report when switching scenarios', async () => {
    render(<App />);

    // 1. Run investigation
    const runBtn = screen.getByRole('button', { name: /Diagnose This Incident/i });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /Repair Options/i })).toBeInTheDocument();
    });

    // 2. Change scenario using scenario dropdown
    const scenarioSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(scenarioSelect, { target: { value: 'index_regression' } });

    // 3. Stale results must be cleared
    expect(screen.queryByRole('tab', { name: /Repair Options/i })).not.toBeInTheDocument();
  });

  it('handles and displays error message when investigation fails', async () => {
    vi.spyOn(api, 'analyzeScenario').mockRejectedValueOnce(new Error('Internal server timeout (504)'));
    render(<App />);

    const runBtn = screen.getByRole('button', { name: /Diagnose This Incident/i });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(screen.getByText(/Internal server timeout \(504\)/i)).toBeInTheDocument();
    });
  });
});
