import React, { useEffect, useState, useRef } from 'react';
import {
  AlertTriangle,
  Info,
  RefreshCw,
  FileText,
  HelpCircle,
  ShieldCheck,
  Clock,
  Database,
} from 'lucide-react';
import { analyzeScenario, fetchHealth, fetchScenarios, generateIncident } from './api';
import type {
  AnalysisResult,
  HealthResponse,
  ScenarioMetadata,
} from './types';
import { Header } from './components/Header';
import { ScenarioBar } from './components/ScenarioBar';
import { OverviewSummary } from './components/OverviewSummary';
import { InvestigationLifecycleStepper } from './components/InvestigationLifecycleStepper';
import { ScopeTensionsPanel } from './components/ScopeTensionsPanel';
import { HypothesesInspector } from './components/HypothesesInspector';
import { StrategyMatrix } from './components/StrategyMatrix';
import { EvidenceLedger } from './components/EvidenceLedger';
import { DiagnosticSplashScreen } from './components/DiagnosticSplashScreen';
import { ErrorBoundary } from './components/ErrorBoundary';

export type DashboardTab = 'overview' | 'causes' | 'repair' | 'timeline' | 'evidence';

export const App: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioMetadata[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>('cache_invalidation_lag');
  const [loading, setLoading] = useState<boolean>(false);
  const [generating, setGenerating] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [activeTab, setActiveTab] = useState<DashboardTab>('overview');

  // Replay timeline state
  const [replayIndex, setReplayIndex] = useState<number>(0);
  const [isReplaying, setIsReplaying] = useState<boolean>(false);

  // Selected evidence highlight for cross-component focus
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);

  const evidenceLedgerRef = useRef<HTMLDivElement>(null);
  const tabButtonRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Initial bootstrap function
  const bootstrapApp = async () => {
    setBootstrapError(null);
    try {
      const [healthData, scenariosData] = await Promise.all([
        fetchHealth().catch((err) => {
          console.warn('Health check failed:', err);
          return null;
        }),
        fetchScenarios().catch((err) => {
          console.warn('Failed loading scenarios:', err);
          return [];
        }),
      ]);

      if (healthData) setHealth(healthData);
      if (scenariosData && scenariosData.length > 0) {
        setScenarios(scenariosData);
        setSelectedScenarioId(scenariosData[0].id);
      } else if (!healthData) {
        setBootstrapError('Unable to connect to Faultline backend service. Please ensure the backend is running.');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Backend connection error';
      setBootstrapError(msg);
    }
  };

  useEffect(() => {
    bootstrapApp();
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  const handleScenarioChange = (newId: string) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setSelectedScenarioId(newId);
    setResult(null); // Clear stale results on scenario switch (required by system test invariants)
    setError(null);
    setSelectedEvidenceId(null);
    setIsReplaying(false);
    setActiveTab('overview');
  };

  const handleTriggerNewIncident = async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setGenerating(true);
    setError(null);
    try {
      const newIncident = await generateIncident();
      setScenarios((prev) => {
        const filtered = prev.filter((s) => s.id !== newIncident.id);
        return [newIncident, ...filtered];
      });
      setSelectedScenarioId(newIncident.id);
      setResult(null);
      setSelectedEvidenceId(null);
      setIsReplaying(false);
      setActiveTab('overview');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to generate new incident';
      setError(msg);
    } finally {
      setGenerating(false);
    }
  };

  const handleRunInvestigation = async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoading(true);
    setError(null);
    setResult(null);
    setIsReplaying(false);
    setSelectedEvidenceId(null);
    try {
      const data = await analyzeScenario(selectedScenarioId, controller.signal);
      setResult(data);
      setReplayIndex(data.investigation_trace.length); // Show full timeline by default
      setActiveTab('overview');
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return; // Intentionally cancelled by user action
      }
      const msg = err instanceof Error ? err.message : 'Investigation failed';
      setError(msg);
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        setLoading(false);
      }
    }
  };

  const handleStartReplay = () => {
    if (!result) return;
    setActiveTab('timeline');
    setReplayIndex(1);
    setIsReplaying(true);
  };

  const handleToggleReplay = () => {
    if (!result) return;
    if (isReplaying) {
      setIsReplaying(false);
    } else {
      if (replayIndex >= result.investigation_trace.length) {
        setReplayIndex(1);
      }
      setIsReplaying(true);
    }
  };

  const handleResetReplay = () => {
    setIsReplaying(false);
    setReplayIndex(1);
  };

  const handleSetReplayIndex = (idx: number) => {
    setIsReplaying(false);
    setReplayIndex(idx);
  };

  const handleSelectEvidence = (evidenceId: string | null) => {
    setSelectedEvidenceId(evidenceId);
    if (evidenceId) {
      setActiveTab('evidence');
      setTimeout(() => {
        if (evidenceLedgerRef.current) {
          evidenceLedgerRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      }, 50);
    }
  };

  // Replay timer effect with speed multiplier
  const [replaySpeed, setReplaySpeed] = useState<number>(1);

  useEffect(() => {
    if (!isReplaying || !result) return;
    if (replayIndex >= result.investigation_trace.length) {
      setIsReplaying(false);
      return;
    }
    const delay = Math.max(200, Math.round(550 / replaySpeed));
    const timer = setTimeout(() => {
      setReplayIndex((prev) => prev + 1);
    }, delay);
    return () => clearTimeout(timer);
  }, [isReplaying, replayIndex, result, replaySpeed]);

  const tabsList: { id: DashboardTab; label: string; icon: React.FC<{ size?: number }>; count?: number }[] = [
    { id: 'overview', label: 'Overview', icon: FileText },
    { id: 'causes', label: 'Root Causes', icon: HelpCircle, count: result?.hypotheses.length },
    { id: 'repair', label: 'Repair Options', icon: ShieldCheck, count: result?.strategy_ranking.length },
    { id: 'timeline', label: 'Timeline Trace', icon: Clock, count: result?.investigation_trace.length },
    { id: 'evidence', label: 'Evidence', icon: Database, count: result?.evidence.length },
  ];

  const handleTabKeyDown = (e: React.KeyboardEvent, currentTab: DashboardTab) => {
    const currentIndex = tabsList.findIndex((t) => t.id === currentTab);
    let nextIndex = currentIndex;
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      nextIndex = (currentIndex + 1) % tabsList.length;
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      nextIndex = (currentIndex - 1 + tabsList.length) % tabsList.length;
    } else if (e.key === 'Home') {
      e.preventDefault();
      nextIndex = 0;
    } else if (e.key === 'End') {
      e.preventDefault();
      nextIndex = tabsList.length - 1;
    }

    if (nextIndex !== currentIndex) {
      setActiveTab(tabsList[nextIndex].id);
      tabButtonRefs.current[nextIndex]?.focus();
    }
  };

  return (
    <div className="app-container">
      {/* Live accessibility region for announcements */}
      <div className="sr-only" role="status" aria-live="polite">
        {loading ? 'Diagnosing incident in real time...' : result ? 'Diagnosis complete. Report ready.' : ''}
      </div>

      <Header health={health} result={result} />

      {/* Bootstrap Connection Error Banner */}
      {bootstrapError && (
        <div className="error-banner" role="alert">
          <div className="error-icon-wrap">
            <AlertTriangle size={18} />
          </div>
          <div className="error-content">
            <div className="error-title">Backend Connection Error</div>
            <div className="error-message">{bootstrapError}</div>
          </div>
          <button className="error-retry-btn" onClick={bootstrapApp}>
            <RefreshCw size={13} /> Reconnect
          </button>
        </div>
      )}

      {/* Main Scenario Selector & Run Actions */}
      <ScenarioBar
        scenarios={scenarios}
        selectedScenarioId={selectedScenarioId}
        onScenarioChange={handleScenarioChange}
        onRunInvestigation={handleRunInvestigation}
        onTriggerNewIncident={handleTriggerNewIncident}
        onStartReplay={handleStartReplay}
        loading={loading}
        generating={generating}
        isReplaying={isReplaying}
        health={health}
        result={result}
      />

      {/* Investigation Error Banner */}
      {error && (
        <div className="error-banner" role="alert">
          <div className="error-icon-wrap">
            <AlertTriangle size={18} />
          </div>
          <div className="error-content">
            <div className="error-title">Investigation Failed</div>
            <div className="error-message">{error}</div>
          </div>
          <button className="error-retry-btn" onClick={handleRunInvestigation}>
            <RefreshCw size={13} /> Retry
          </button>
        </div>
      )}

      {/* Initial Empty / Idle State */}
      {!result && !loading && !error && (
        <div className="idle-state-card">
          <div className="idle-content">
            <div className="idle-icon-wrap">
              <Info size={28} className="text-cyan" />
            </div>
            <h3 className="idle-title">Ready to Investigate</h3>
            <p className="idle-desc">
              Select an active incident or click <strong>Trigger New Incident</strong> to generate a fresh outage on demand, then click <strong>Diagnose This Incident</strong> to find out what went wrong, why, and how to fix it.
            </p>
          </div>
        </div>
      )}

      {/* Real-Time Diagnostic Splash Screen */}
      {loading && (
        <DiagnosticSplashScreen
          scenarioTitle={scenarios.find((s) => s.id === selectedScenarioId)?.title}
        />
      )}

      {/* Active Verified Investigation Results (Multi-Tab Dashboard) */}
      {result && (
        <ErrorBoundary fallbackTitle="Dashboard Display Error">
          <main className="dashboard-main-view" aria-label="Investigation Dashboard">
            {/* Dashboard Tab Navigation Bar */}
            <div className="dashboard-tabs-bar" role="tablist" aria-label="Incident Investigation Sections">
              {tabsList.map((tab, idx) => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    ref={(el) => { tabButtonRefs.current[idx] = el; }}
                    id={`tab-btn-${tab.id}`}
                    className={`dashboard-tab-btn ${isActive ? 'tab-active' : ''}`}
                    role="tab"
                    aria-selected={isActive}
                    aria-controls={`tab-panel-${tab.id}`}
                    tabIndex={isActive ? 0 : -1}
                    onClick={() => setActiveTab(tab.id)}
                    onKeyDown={(e) => handleTabKeyDown(e, tab.id)}
                  >
                    <Icon size={14} />
                    <span>{tab.label}</span>
                    {tab.count !== undefined && (
                      <span className="tab-badge font-mono">{tab.count}</span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* TAB 1: Summary & Action */}
            {activeTab === 'overview' && (
              <div
                id="tab-panel-overview"
                role="tabpanel"
                aria-labelledby="tab-btn-overview"
                className="tab-panel"
              >
                <OverviewSummary
                  result={result}
                  onNavigateTab={(tab) => {
                    setActiveTab(tab);
                    const tabIndex = tabsList.findIndex((t) => t.id === tab);
                    if (tabIndex >= 0) {
                      tabButtonRefs.current[tabIndex]?.focus();
                    }
                  }}
                  onSelectEvidence={handleSelectEvidence}
                />
              </div>
            )}

            {/* TAB 2: Possible Causes & Contradictions */}
            {activeTab === 'causes' && (
              <div
                id="tab-panel-causes"
                role="tabpanel"
                aria-labelledby="tab-btn-causes"
                className="tab-panel"
              >
                <div className="causes-flow">
                  <HypothesesInspector
                    hypotheses={result.hypotheses}
                    onSelectEvidence={handleSelectEvidence}
                  />
                  <ScopeTensionsPanel
                    conflicts={result.conflicts}
                    evidenceList={result.evidence}
                    onSelectEvidence={handleSelectEvidence}
                  />
                </div>
              </div>
            )}

            {/* TAB 3: Recommended Repair Strategies */}
            {activeTab === 'repair' && (
              <div
                id="tab-panel-repair"
                role="tabpanel"
                aria-labelledby="tab-btn-repair"
                className="tab-panel"
              >
                <StrategyMatrix
                  strategies={result.strategy_ranking}
                  winningStrategyId={result.recommendation.grounding?.winning_strategy_id}
                />
              </div>
            )}

            {/* TAB 4: Investigation Steps Timeline */}
            {activeTab === 'timeline' && (
              <div
                id="tab-panel-timeline"
                role="tabpanel"
                aria-labelledby="tab-btn-timeline"
                className="tab-panel"
              >
                <InvestigationLifecycleStepper
                  trace={result.investigation_trace}
                  replayIndex={replayIndex}
                  isReplaying={isReplaying}
                  onToggleReplay={handleToggleReplay}
                  onResetReplay={handleResetReplay}
                  onSetReplayIndex={handleSetReplayIndex}
                  replaySpeed={replaySpeed}
                  onSetReplaySpeed={setReplaySpeed}
                  runId={result.run_id}
                  validationPassed={result.validation_passed}
                />
              </div>
            )}

            {/* TAB 5: All Collected Evidence Ledger */}
            {activeTab === 'evidence' && (
              <div
                id="tab-panel-evidence"
                role="tabpanel"
                aria-labelledby="tab-btn-evidence"
                className="tab-panel"
                ref={evidenceLedgerRef}
              >
                <EvidenceLedger
                  evidence={result.evidence}
                  conflicts={result.conflicts}
                  selectedEvidenceId={selectedEvidenceId}
                  onClearSelectedEvidence={() => setSelectedEvidenceId(null)}
                />
              </div>
            )}
          </main>
        </ErrorBoundary>
      )}
    </div>
  );
};

export default App;
