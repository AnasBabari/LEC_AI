import type { AnalysisResult, HealthResponse, ScenarioMetadata } from './types';

const API_BASE = '';

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) {
    throw new Error(`Health check failed: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchScenarios(): Promise<ScenarioMetadata[]> {
  const res = await fetch(`${API_BASE}/api/scenarios`);
  if (!res.ok) {
    throw new Error(`Failed to load scenarios: ${res.statusText}`);
  }
  return res.json();
}

export async function analyzeScenario(
  scenarioId: string,
  signal?: AbortSignal
): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario_id: scenarioId }),
    signal,
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(errorData.detail || `Analysis failed with status ${res.status}`);
  }
  return res.json();
}
