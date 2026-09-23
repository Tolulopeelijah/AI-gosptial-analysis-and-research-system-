import { cn } from '@/lib/cn'
import { useQueryState } from '@/state/QueryProvider'
import { Button } from '@/components/ui/Button'
import { AlertIcon, InfoIcon, RefreshIcon } from '@/components/ui/Icons'
import type { GeoErrorCode, GeoQueryError } from '@/types/agent'

/**
 * Error presentation.
 *
 * Every failure code gets its own heading, explanation and suggested next step,
 * because the codes mean genuinely different things to the person reading them:
 * "the service is down" and "that dataset isn't loaded" call for different
 * actions. There is deliberately no generic "Something went wrong" path — an
 * unrecognised code falls back to the code string itself rather than a vague
 * sentence.
 */
interface ErrorCopy {
  title: string
  /** What happened, in the tool's own terms. */
  body: string
  /** What to do about it. */
  action?: string
  tone: 'warning' | 'critical'
  /** Pre-filled queries offered as a way out. */
  suggestions?: string[]
}

const ERROR_COPY: Record<GeoErrorCode, ErrorCopy> = {
  backend_unavailable: {
    title: 'Geospatial service unreachable',
    body: 'The request never reached the backend — no dataset was loaded and no GIS operation ran.',
    action:
      'Start the backend (`python server.py`) and check VITE_GEO_API_URL, then try again.',
    tone: 'critical',
  },
  data_unavailable: {
    title: 'Requested dataset is not loaded',
    body: 'A dataset the query depends on is not registered with this instance, so the operation cannot be executed.',
    action: 'Rephrase using a dataset this instance holds, or register the missing layer.',
    tone: 'warning',
  },
  invalid_geographic_query: {
    title: 'No geographic operation identified',
    body: 'The query could not be resolved into a dataset plus an operation. This usually means the place, attribute or spatial relation was not recognised.',
    action: 'Name a place, a dataset and a condition — for example a population threshold or a distance.',
    tone: 'warning',
    suggestions: ['Show counties in Texas', 'Find counties within 50 km of Dallas'],
  },
  no_results: {
    title: 'No features matched',
    body: 'The query was valid and executed against the dataset, but nothing satisfied every condition.',
    action: 'Loosen a threshold or widen the geographic extent.',
    tone: 'warning',
  },
  processing_error: {
    title: 'A GIS operation failed mid-plan',
    body: 'The plan started executing and one of its tool calls returned an error, so the result set is incomplete. Steps that completed before the failure are shown above.',
    action: 'Re-run the query; if it fails at the same step, the input geometry is the likely cause.',
    tone: 'critical',
  },
  timeout: {
    title: 'Query exceeded its time budget',
    body: 'The operation was still running when the deadline passed, and was stopped before it produced results.',
    action: 'Narrow the extent or raise a threshold so fewer features are processed.',
    tone: 'warning',
  },
  query_failed: {
    title: 'Query failed',
    body: 'The service returned a failure without a more specific code.',
    action: 'Check the technical detail below and re-run.',
    tone: 'critical',
  },
  aborted: {
    title: 'Query cancelled',
    body: 'The run was stopped before it finished. No partial results were kept.',
    action: 'Run it again when you are ready.',
    tone: 'warning',
  },
}

export function ErrorNotice({ error, query }: { error: GeoQueryError; query: string }) {
  const { fillDraft } = useQueryState()
  const copy = ERROR_COPY[error.code]
  const isCritical = copy.tone === 'critical'

  return (
    <div
      className={cn(
        'border px-3 py-2.5',
        isCritical ? 'border-critical/35 bg-critical/6' : 'border-warning/45 bg-warning/8',
      )}
      role="alert"
    >
      <div className="flex items-start gap-2">
        <span className={cn('mt-[1px] shrink-0', isCritical ? 'text-critical' : 'text-ink')}>
          {isCritical ? <AlertIcon size={15} /> : <InfoIcon size={15} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <h3 className="text-[13px] font-semibold text-ink">{copy.title}</h3>
            <code className="font-mono text-[10px] text-ink-3">{error.code}</code>
          </div>

          <p className="mt-1 text-[12px] leading-relaxed text-ink-2">{copy.body}</p>

          {/* The backend's own message often carries the specific detail — which
              state is missing, which place was not found — so it is shown
              verbatim rather than replaced by the copy above. */}
          {error.message && error.message !== copy.title ? (
            <p className="mt-1.5 border-l-2 border-line-strong pl-2 text-[12px] leading-snug text-ink">
              {error.message}
            </p>
          ) : null}

          {(error.hint ?? copy.action) ? (
            <p className="mt-1.5 text-[12px] leading-snug text-ink-2">
              <span className="font-medium text-ink">Next: </span>
              {error.hint ?? copy.action}
            </p>
          ) : null}

          {error.detail ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-[11px] text-ink-3 hover:text-ink-2">
                Technical detail
              </summary>
              <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words border border-line bg-panel-sunken px-2 py-1.5 font-mono text-[10px] leading-snug text-ink-2">
                {error.detail}
              </pre>
            </details>
          ) : null}

          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {query ? (
              <Button size="sm" variant="default" icon={<RefreshIcon size={13} />} onClick={() => fillDraft(query)}>
                Edit and re-run
              </Button>
            ) : null}
            {copy.suggestions?.map((suggestion) => (
              <Button key={suggestion} size="sm" variant="ghost" onClick={() => fillDraft(suggestion)}>
                {suggestion}
              </Button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
