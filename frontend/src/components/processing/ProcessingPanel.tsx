import { cn } from '@/lib/cn'
import { summarizeSteps } from '@/services/agentSteps'
import { formatDuration } from '@/lib/format'
import { useQueryState } from '@/state/QueryProvider'
import { Panel, StatusBadge } from '@/components/ui/Panel'
import { Spinner } from '@/components/ui/Button'
import { AgentIcon, AlertIcon, CheckIcon } from '@/components/ui/Icons'
import type { ProcessingStep, StepStatus } from '@/types/agent'

/**
 * The processing panel.
 *
 * Reads `ProcessingStep[]` and nothing else — it has no knowledge of
 * `AgentEvent`, so a real SSE or WebSocket feed only has to produce the same
 * events to drive this unchanged.
 *
 * The planner's whole task list is rendered as soon as it is known, with the
 * later steps pending, so the panel shows the shape of the work rather than
 * only its history.
 */
export function ProcessingPanel() {
  const { run, isRunning } = useQueryState().query
  const { steps, messages, status, error, startedAt, finishedAt } = run

  const summary = summarizeSteps(steps)
  const elapsed =
    startedAt != null ? (finishedAt ?? Date.now()) - startedAt : undefined

  const idle = status === 'idle'

  return (
    <Panel
      title="Processing"
      icon={<AgentIcon size={14} />}
      actions={
        steps.length > 0 ? (
          <span className="font-mono text-[10px] tabular-nums text-ink-3">
            {summary.done}/{summary.total}
          </span>
        ) : null
      }
      className="shrink-0"
    >
      {idle ? (
        <p className="text-[12px] leading-relaxed text-ink-3">
          The agent's plan and tool calls appear here while a query runs — query understanding,
          dataset resolution, then each GIS operation in turn.
        </p>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusBadge tone={statusTone(status)} dot>
              {statusLabel(status)}
            </StatusBadge>
            {summary.failed > 0 ? (
              <StatusBadge tone="critical">{summary.failed} step failed</StatusBadge>
            ) : null}
            {elapsed != null && !isRunning ? (
              <span className="font-mono text-[10px] tabular-nums text-ink-3">
                {formatDuration(elapsed)}
              </span>
            ) : null}
          </div>

          {messages.length > 0 ? (
            <p className="border-l-2 border-line-strong pl-2 text-[11px] leading-snug text-ink-2">
              {messages[messages.length - 1]}
            </p>
          ) : null}

          <ol className="space-y-px">
            {steps.map((step) => (
              <StepRow key={step.id} step={step} />
            ))}
          </ol>

          {steps.length === 0 && isRunning ? (
            <p className="text-[12px] text-ink-3">Waiting for the first event…</p>
          ) : null}

          {error ? (
            <div className="border border-critical/35 bg-critical/6 px-2 py-1.5">
              <div className="flex items-center gap-1.5 text-[11px] font-medium text-critical">
                <AlertIcon size={13} />
                <span className="font-mono">{error.code}</span>
              </div>
              {error.detail ? (
                <p className="mt-1 font-mono text-[10px] leading-snug break-words text-ink-2">
                  {error.detail}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </Panel>
  )
}

function statusTone(status: string): 'neutral' | 'accent' | 'good' | 'critical' {
  if (status === 'completed') return 'good'
  if (status === 'failed') return 'critical'
  if (status === 'processing' || status === 'submitted') return 'accent'
  return 'neutral'
}

function statusLabel(status: string): string {
  switch (status) {
    case 'submitted':
      return 'Request sent'
    case 'processing':
      return 'Running'
    case 'completed':
      return 'Complete'
    case 'failed':
      return 'Failed'
    default:
      return 'Idle'
  }
}

function StepRow({ step }: { step: ProcessingStep }) {
  return (
    <li className="flex items-start gap-2 py-[3px]">
      <span className="mt-[1px] flex size-3.5 shrink-0 items-center justify-center">
        <StepGlyph status={step.status} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span
            className={cn(
              'min-w-0 truncate text-[12px]',
              step.status === 'pending' && 'text-ink-3',
              step.status === 'active' && 'font-medium text-ink',
              step.status === 'done' && 'text-ink-2',
              step.status === 'failed' && 'text-critical',
            )}
          >
            {step.label}
          </span>
          {step.durationMs != null ? (
            <span className="shrink-0 font-mono text-[10px] tabular-nums text-ink-3">
              {formatDuration(step.durationMs)}
            </span>
          ) : null}
        </div>

        {step.detail ? (
          <p className="mt-0.5 text-[11px] leading-snug text-ink-3">{step.detail}</p>
        ) : null}

        {step.tool && step.status === 'active' ? (
          <p className="mt-0.5 font-mono text-[10px] text-ink-3">{step.tool}()</p>
        ) : null}
      </div>
    </li>
  )
}

/** Status is carried by shape as well as colour, so it survives greyscale. */
function StepGlyph({ status }: { status: StepStatus }) {
  if (status === 'active') return <Spinner className="size-3 text-accent" />
  if (status === 'done') return <CheckIcon size={13} className="text-good" />
  if (status === 'failed') return <AlertIcon size={13} className="text-critical" />
  return (
    <span className="size-1.5 rounded-full border border-line-strong" aria-hidden="true" />
  )
}
