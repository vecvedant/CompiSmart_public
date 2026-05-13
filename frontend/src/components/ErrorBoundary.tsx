import React from "react";
import { AlertTriangle } from "lucide-react";

// Catches render-time exceptions in the subtree and shows a friendly card
// instead of unmounting React (the dreaded white screen). Logs the error +
// component stack to the console so you can still debug from devtools.
interface State {
  err: Error | null;
  info: string | null;
}

export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  State
> {
  state: State = { err: null, info: null };

  static getDerivedStateFromError(err: Error): State {
    return { err, info: null };
  }

  componentDidCatch(err: Error, info: React.ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught:", err, info);
    this.setState({ info: info.componentStack ?? null });
  }

  reset = () => this.setState({ err: null, info: null });

  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-slate-50">
        <div className="max-w-xl w-full bg-white border border-red-200 rounded-3xl p-8 shadow-sm">
          <div className="flex items-center gap-2 text-red-600 mb-3">
            <AlertTriangle className="w-5 h-5" />
            <h2 className="font-bold tracking-tight">Something broke in the UI</h2>
          </div>
          <p className="text-sm text-slate-700 font-mono break-all">
            {this.state.err.message}
          </p>
          {this.state.info && (
            <details className="mt-4 text-xs text-slate-500">
              <summary className="cursor-pointer">Component stack</summary>
              <pre className="mt-2 whitespace-pre-wrap break-all">
                {this.state.info}
              </pre>
            </details>
          )}
          <button
            onClick={this.reset}
            className="mt-6 px-4 py-2 bg-orange-500 text-white rounded-xl font-bold text-sm hover:bg-orange-600 transition-colors"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }
}
