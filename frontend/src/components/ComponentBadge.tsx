import React from 'react';
import { Server, Database, Zap, Layers, HelpCircle } from 'lucide-react';
import type { ComponentEnum } from '../types';

interface ComponentBadgeProps {
  component: ComponentEnum | string;
  size?: 'sm' | 'md' | 'lg';
  showIcon?: boolean;
}

const getComponentConfig = (comp: ComponentEnum | string) => {
  switch (comp) {
    case 'api_gateway':
      return {
        name: 'API Gateway',
        shortName: 'Gateway',
        icon: Server,
        colorClass: 'comp-api-gateway',
        color: '#06b6d4',
      };
    case 'database':
      return {
        name: 'Database',
        shortName: 'Database',
        icon: Database,
        colorClass: 'comp-database',
        color: '#10b981',
      };
    case 'cache':
      return {
        name: 'Cache Cluster',
        shortName: 'Cache',
        icon: Zap,
        colorClass: 'comp-cache',
        color: '#f59e0b',
      };
    case 'message_queue':
      return {
        name: 'Message Queue',
        shortName: 'Queue',
        icon: Layers,
        colorClass: 'comp-message-queue',
        color: '#818cf8',
      };
    default:
      return {
        name: comp,
        shortName: comp,
        icon: HelpCircle,
        colorClass: 'comp-default',
        color: '#94a3b8',
      };
  }
};

export const ComponentBadge: React.FC<ComponentBadgeProps> = ({
  component,
  size = 'md',
  showIcon = true,
}) => {
  const config = getComponentConfig(component);
  const IconComponent = config.icon;
  const iconSize = size === 'sm' ? 11 : size === 'lg' ? 16 : 13;

  return (
    <span className={`comp-badge ${config.colorClass} comp-badge-${size}`}>
      {showIcon && <IconComponent size={iconSize} className="comp-icon" />}
      <span>{config.name}</span>
    </span>
  );
};
