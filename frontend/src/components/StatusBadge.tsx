import React from 'react';
import { CheckCircle2, AlertTriangle, XCircle, Info, HelpCircle } from 'lucide-react';
import type { HealthStatus } from '../types';

interface StatusBadgeProps {
  status: HealthStatus | string;
  size?: 'sm' | 'md';
  showIcon?: boolean;
  label?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  size = 'md',
  showIcon = true,
  label,
}) => {
  const normStatus = status.toLowerCase();

  let badgeClass = 'badge-neutral';
  let IconComponent = HelpCircle;
  let defaultLabel = status;

  if (normStatus === 'healthy' || normStatus === 'pass' || normStatus === 'strong') {
    badgeClass = 'badge-healthy';
    IconComponent = CheckCircle2;
    defaultLabel = label || (normStatus === 'strong' ? 'High Confidence' : 'Healthy');
  } else if (
    normStatus === 'degraded' ||
    normStatus === 'warn' ||
    normStatus === 'moderate' ||
    normStatus === 'weak'
  ) {
    badgeClass = 'badge-degraded';
    IconComponent = AlertTriangle;
    defaultLabel = label || (normStatus === 'moderate' ? 'Moderate Confidence' : normStatus === 'weak' ? 'Low Confidence' : 'Degraded');
  } else if (normStatus === 'failed' || normStatus === 'critical' || normStatus === 'unsupported') {
    badgeClass = 'badge-failed';
    IconComponent = XCircle;
    defaultLabel = label || (normStatus === 'unsupported' ? 'Insufficient Data' : 'Issue Found');
  } else if (normStatus === 'informational' || normStatus === 'advisory') {
    badgeClass = 'badge-primary';
    IconComponent = Info;
    defaultLabel = label || 'Info';
  }

  const iconSize = size === 'sm' ? 11 : 13;

  return (
    <span className={`badge ${badgeClass} ${size === 'sm' ? 'badge-sm' : ''}`}>
      {showIcon && <IconComponent size={iconSize} />}
      <span>{label || defaultLabel}</span>
    </span>
  );
};
