import React, { useState } from 'react';
import {
  Copy,
  Check,
  Lock,
  AlertTriangle,
} from 'lucide-react';
import type { ExecutionSafetySection } from '../types';

interface SafetyConsoleProps {
  execution?: ExecutionSafetySection;
}

export const SafetyConsole: React.FC<SafetyConsoleProps> = ({ execution }) => {
  const [copied, setCopied] = useState<boolean>(false);
  const [checkedPreconditions, setCheckedPreconditions] = useState<Record<number, boolean>>({});

  const suggestedCommand = execution?.suggested_command || 'No command proposed';
  const preconditions = execution?.safety_preconditions || [];

  const handleCopy = () => {
    if (!suggestedCommand) return;
    navigator.clipboard.writeText(suggestedCommand);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const togglePrecondition = (idx: number) => {
    setCheckedPreconditions((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const allPreconditionsChecked =
    preconditions.length > 0 &&
    preconditions.every((_, idx) => !!checkedPreconditions[idx]);

  return (
    <footer className="safety-console-container" role="region" aria-label="Remediation and Safety Console">
      <div className="safety-console-header">
        <div className="safety-status-badge">
          <div className="safety-lock-icon">
            <Lock size={15} />
          </div>
          <div>
            <div className="safety-badge-title font-mono">
              Safety First: Review Before Running
            </div>
            <div className="safety-badge-subtitle">
              No changes have been made to your system. Review the command and checklist below before taking action.
            </div>
          </div>
        </div>

        <div className="execution-status-pill font-mono">
          <span className="status-dot dot-amber" />
          <span>Status: {execution?.execution_status === 'not_executed' ? 'Ready for your review' : (execution?.execution_status || 'Not executed')}</span>
        </div>
      </div>

      {/* Suggested Command */}
      <div className="safety-command-box">
        <div className="command-box-topbar">
          <div className="terminal-dots">
            <span className="term-dot dot-red" />
            <span className="term-dot dot-yellow" />
            <span className="term-dot dot-green" />
            <span className="terminal-label">Suggested remediation command</span>
          </div>

          <button
            className="btn-copy-command font-mono"
            onClick={handleCopy}
            title="Copy command to clipboard"
            aria-label="Copy suggested remediation command"
          >
            {copied ? (
              <>
                <Check size={12} className="text-emerald" />
                <span>Copied!</span>
              </>
            ) : (
              <>
                <Copy size={12} />
                <span>Copy Command</span>
              </>
            )}
          </button>
        </div>

        <div className="command-terminal-body">
          <div className="terminal-prefix font-mono">$</div>
          <code className="terminal-code font-mono">{suggestedCommand}</code>
        </div>
      </div>

      {/* Safety Checklist */}
      {preconditions.length > 0 && (
        <div className="safety-preconditions-section">
          <div className="preconditions-header">
            <AlertTriangle size={13} className="text-amber" />
            <span>Before running this command, verify:</span>
          </div>

          <fieldset className="preconditions-checklist" style={{ border: 'none', padding: 0, margin: 0 }}>
            <legend className="sr-only">Required safety verification checklist</legend>
            {preconditions.map((p, idx) => {
              const isChecked = !!checkedPreconditions[idx];
              return (
                <label
                  key={idx}
                  className={`precondition-item ${isChecked ? 'item-checked' : ''}`}
                >
                  <input
                    type="checkbox"
                    className="precondition-checkbox"
                    checked={isChecked}
                    onChange={() => togglePrecondition(idx)}
                    aria-label={`Verify precondition: ${p}`}
                  />
                  <span className="precondition-text">{p}</span>
                </label>
              );
            })}
          </fieldset>

          {allPreconditionsChecked && (
            <div className="preconditions-verified-note font-mono text-emerald" role="status">
              <Check size={13} /> All listed preconditions marked as reviewed. Operator approval is still required.
            </div>
          )}
        </div>
      )}
    </footer>
  );
};
