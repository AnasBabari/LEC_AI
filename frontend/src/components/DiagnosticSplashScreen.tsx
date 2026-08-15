import React, { useEffect, useState } from 'react';
import {
  Activity,
  CheckCircle2,
  Layers,
  Loader2,
  Radio,
  Scale,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

interface DiagnosticSplashScreenProps {
  scenarioTitle?: string;
}

interface StepInfo {
  id: number;
  title: string;
  detail: string;
  icon: React.ElementType;
}

const STEPS: StepInfo[] = [
  {
    id: 1,
    title: 'Checking System Health & Logs',
    detail: 'Gathering server metrics, health checks, and recent operational alerts...',
    icon: Radio,
  },
  {
    id: 2,
    title: 'Comparing Live Traffic vs Direct Probes',
    detail: 'Checking if servers respond directly versus under live user load...',
    icon: Layers,
  },
  {
    id: 3,
    title: 'Finding What Went Wrong',
    detail: 'Analyzing incident patterns to identify the most likely root causes...',
    icon: Sparkles,
  },
  {
    id: 4,
    title: 'Selecting the Best Recovery Option',
    detail: 'Comparing fix actions by speed, safety, and effectiveness...',
    icon: Scale,
  },
  {
    id: 5,
    title: 'Preparing Safe Action Plan',
    detail: 'Generating step-by-step verification and commands for operators...',
    icon: ShieldCheck,
  },
];

export const DiagnosticSplashScreen: React.FC<DiagnosticSplashScreenProps> = ({
  scenarioTitle = 'Incident Diagnosis',
}) => {
  const [currentStepIndex, setCurrentStepIndex] = useState<number>(0);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    // Progress through steps based on typical elapsed seconds
    const interval = setInterval(() => {
      setCurrentStepIndex((prev) => {
        if (prev < STEPS.length - 1) {
          return prev + 1;
        }
        return prev;
      });
    }, 2800);
    return () => clearInterval(interval);
  }, []);

  const activeStep = STEPS[currentStepIndex];

  return (
    <div
      className="diagnostic-splash-overlay"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Diagnosing incident in real-time"
    >
      <div className="diagnostic-splash-card card">
        {/* Animated Pulse Orb */}
        <div className="splash-orb-container">
          <div className="splash-orb-ring" />
          <div className="splash-orb-core">
            <Activity size={28} className="splash-orb-icon text-cyan" />
          </div>
        </div>

        {/* Title & Status */}
        <div className="splash-header-text">
          <div className="splash-badge font-mono">
            <Loader2 size={12} className="animate-spin text-cyan" />
            <span>DIAGNOSING INCIDENT • {elapsedSeconds}s</span>
          </div>
          <h2 className="splash-title">Analyzing Incident in Real-Time</h2>
          <p className="splash-scenario-name">{scenarioTitle}</p>
        </div>

        {/* Current Active Phase Callout */}
        <div className="splash-active-phase-box font-mono">
          <div className="splash-phase-indicator">
            <span className="status-dot dot-healthy dot-pulse" />
            <span className="splash-phase-label">CURRENT STEP:</span>
            <span className="splash-phase-name">{activeStep.title}</span>
          </div>
          <p className="splash-phase-detail font-sans">{activeStep.detail}</p>
        </div>

        {/* Interactive Step Progression List */}
        <div className="splash-steps-list">
          {STEPS.map((step, idx) => {
            const isCompleted = idx < currentStepIndex;
            const isCurrent = idx === currentStepIndex;
            const StepIcon = step.icon;

            return (
              <div
                key={step.id}
                className={`splash-step-item ${isCompleted ? 'step-done' : ''} ${
                  isCurrent ? 'step-active' : ''
                }`}
              >
                <div className="splash-step-icon-wrap">
                  {isCompleted ? (
                    <CheckCircle2 size={16} className="text-emerald" />
                  ) : isCurrent ? (
                    <Loader2 size={16} className="animate-spin text-cyan" />
                  ) : (
                    <StepIcon size={14} className="text-muted" />
                  )}
                </div>
                <div className="splash-step-info">
                  <div className="splash-step-title">{step.title}</div>
                </div>
                <div className="splash-step-status font-mono">
                  {isCompleted ? 'Done' : isCurrent ? 'Active...' : 'Pending'}
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer Subtext */}
        <div className="splash-footer-note font-mono">
          <span>Faultline AI Incident Advisor • Human review required before taking action</span>
        </div>
      </div>
    </div>
  );
};
