import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertOctagon, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public override state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public override componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('Uncaught error in component tree:', error, errorInfo);
  }

  public handleReload = (): void => {
    window.location.reload();
  };

  public handleReset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  public override render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          aria-live="assertive"
          className="glass-card"
          style={{
            maxWidth: '680px',
            margin: '4rem auto',
            padding: '2.5rem',
            textAlign: 'center',
            borderColor: 'rgba(239, 68, 68, 0.4)',
            background: 'rgba(15, 23, 42, 0.9)',
          }}
        >
          <div
            style={{
              display: 'inline-flex',
              padding: '1rem',
              borderRadius: '50%',
              background: 'rgba(239, 68, 68, 0.15)',
              color: '#ef4444',
              marginBottom: '1.25rem',
            }}
          >
            <AlertOctagon size={36} />
          </div>

          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#f8fafc', marginBottom: '0.75rem' }}>
            {this.props.fallbackTitle || 'Unexpected Dashboard Error'}
          </h2>

          <p style={{ color: '#94a3b8', fontSize: '0.95rem', lineHeight: 1.6, marginBottom: '1.5rem' }}>
            {this.state.error?.message || 'An unexpected error occurred while rendering this view.'}
          </p>

          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center' }}>
            <button
              type="button"
              onClick={this.handleReset}
              className="btn btn-secondary"
              style={{ padding: '0.625rem 1.25rem' }}
            >
              Try Again
            </button>
            <button
              type="button"
              onClick={this.handleReload}
              className="btn btn-primary"
              style={{ padding: '0.625rem 1.25rem', display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
            >
              <RefreshCw size={16} />
              Reload Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
