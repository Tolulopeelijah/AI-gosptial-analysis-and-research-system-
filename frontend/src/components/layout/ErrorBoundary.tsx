import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * Last-resort boundary.
 *
 * A rendering fault in the map or a panel should not leave a blank page: the
 * failure is stated, the stack is available behind a disclosure, and the user
 * can reset the interface without reloading.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[geoscope] unhandled render error', error, info.componentStack)
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="flex min-h-dvh items-center justify-center bg-canvas p-6">
        <div className="w-full max-w-lg border border-critical/40 bg-panel p-4">
          <h1 className="text-[14px] font-semibold text-ink">The interface stopped rendering</h1>
          <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">
            A component threw while rendering. This is a frontend fault, not a failure of the
            geospatial service — no query was affected.
          </p>
          <p className="mt-2 border-l-2 border-critical/50 pl-2 font-mono text-[11px] break-words text-ink">
            {error.message}
          </p>
          <details className="mt-2">
            <summary className="cursor-pointer text-[11px] text-ink-3 hover:text-ink-2">
              Stack trace
            </summary>
            <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words border border-line bg-panel-sunken px-2 py-1.5 font-mono text-[10px] leading-snug text-ink-2">
              {error.stack ?? 'No stack trace available.'}
            </pre>
          </details>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="mt-3 inline-flex h-8 items-center rounded-[3px] border border-line-strong bg-panel px-3 text-[12px] font-medium text-ink hover:bg-panel-muted"
          >
            Try rendering again
          </button>
        </div>
      </div>
    )
  }
}
