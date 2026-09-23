import type { AgentEvent, ProcessingStep, StepKind } from '@/types/agent'

/**
 * Turns the agent event stream into the step list the processing panel renders.
 *
 * The panel never sees an `AgentEvent` — it renders `ProcessingStep[]`. That
 * keeps the presentation layer independent of the transport, and means a real
 * SSE/WebSocket feed only has to emit the same events.
 */

interface ToolDescriptor {
  label: string
  kind: StepKind
}

/** Friendly labels for the GIS tools the agent can call. */
const TOOL_DESCRIPTORS: Record<string, ToolDescriptor> = {
  parse_query: { label: 'Understanding query', kind: 'understand' },
  resolve_dataset: { label: 'Identifying required dataset', kind: 'dataset' },
  load_dataset: { label: 'Loading dataset', kind: 'dataset' },
  geocode: { label: 'Resolving place name', kind: 'dataset' },
  boundary_filter: { label: 'Executing boundary filter', kind: 'tool' },
  attribute_filter: { label: 'Executing attribute filter', kind: 'tool' },
  buffer: { label: 'Executing spatial query', kind: 'tool' },
  intersect: { label: 'Executing spatial intersection', kind: 'tool' },
  prepare_results: { label: 'Preparing map results', kind: 'result' },
}

export function describeTool(tool: string): ToolDescriptor {
  return TOOL_DESCRIPTORS[tool] ?? { label: humanizeTool(tool), kind: 'tool' }
}

function humanizeTool(tool: string): string {
  const words = tool.replace(/[_-]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

let stepSequence = 0
function nextStepId(prefix: string): string {
  stepSequence += 1
  return `${prefix}-${stepSequence}`
}

/** Test hook so ids stay deterministic between runs. */
export function resetStepSequence(): void {
  stepSequence = 0
}

function withStatus(
  steps: ProcessingStep[],
  predicate: (step: ProcessingStep) => boolean,
  update: (step: ProcessingStep) => ProcessingStep,
): ProcessingStep[] {
  let applied = false
  return steps.map((step) => {
    // Only the first match is updated: a tool can appear once per plan.
    if (applied || !predicate(step)) return step
    applied = true
    return update(step)
  })
}

/**
 * Folds one event into the step list.
 *
 * Pure: returns a new array and never mutates the input, so it drops straight
 * into a reducer.
 */
export function applyAgentEvent(steps: ProcessingStep[], event: AgentEvent): ProcessingStep[] {
  switch (event.type) {
    case 'query_received': {
      const already = steps.find((step) => step.kind === 'understand')
      if (already) {
        return withStatus(
          steps,
          (step) => step.kind === 'understand',
          (step) => ({ ...step, status: 'active' }),
        )
      }
      return [
        ...steps,
        {
          id: nextStepId('understand'),
          label: 'Understanding query',
          kind: 'understand',
          status: 'active',
        },
      ]
    }

    case 'planning': {
      // Everything the understand phase covered is now settled.
      let next = steps.map((step) =>
        step.status === 'active' ? { ...step, status: 'done' as const } : step,
      )

      next = [
        ...next,
        {
          id: nextStepId('plan'),
          label: 'Planning GIS operations',
          kind: 'plan',
          status: 'active',
          detail: event.message,
        },
      ]

      // The planner can name the tasks it intends to run; render them up front
      // as pending so the user sees the whole plan, not just what has happened.
      if (event.plan?.length) {
        for (const task of event.plan) {
          const descriptor = describeTool(task.tool)
          next.push({
            id: task.id,
            label: task.label || descriptor.label,
            kind: descriptor.kind,
            status: 'pending',
            tool: task.tool,
          })
        }
      }
      return next
    }

    case 'tool_call': {
      if (event.status === 'started') {
        const pendingMatch = steps.find(
          (step) => step.tool === event.tool && step.status === 'pending',
        )
        if (pendingMatch) {
          return withStatus(
            steps,
            (step) => step.id === pendingMatch.id,
            (step) => ({ ...step, status: 'active' }),
          )
        }
        const descriptor = describeTool(event.tool)
        return [
          ...steps,
          {
            id: nextStepId('tool'),
            label: descriptor.label,
            kind: descriptor.kind,
            status: 'active',
            tool: event.tool,
          },
        ]
      }

      const target = steps.find(
        (step) => step.tool === event.tool && step.status !== 'done' && step.status !== 'failed',
      )
      const status = event.status === 'completed' ? ('done' as const) : ('failed' as const)

      if (!target) {
        const descriptor = describeTool(event.tool)
        return [
          ...steps,
          {
            id: nextStepId('tool'),
            label: descriptor.label,
            kind: descriptor.kind,
            status,
            tool: event.tool,
            detail: event.message,
            durationMs: event.durationMs,
          },
        ]
      }

      return steps.map((step) =>
        step.id === target.id
          ? {
              ...step,
              status,
              detail: event.message ?? step.detail,
              durationMs: event.durationMs ?? step.durationMs,
            }
          : step,
      )
    }

    case 'result':
      // Results land on the map; the step list already covers this phase.
      return steps

    case 'completed':
      return steps.map((step) =>
        step.status === 'active' ? { ...step, status: 'done' as const } : step,
      )

    case 'error':
      return steps.map((step) =>
        step.status === 'active' ? { ...step, status: 'failed' as const } : step,
      )

    default:
      return steps
  }
}

/** Counts used by the panel header, e.g. "3 of 5 complete". */
export function summarizeSteps(steps: ProcessingStep[]): {
  total: number
  done: number
  failed: number
  active: ProcessingStep | null
} {
  let done = 0
  let failed = 0
  let active: ProcessingStep | null = null
  for (const step of steps) {
    if (step.status === 'done') done++
    else if (step.status === 'failed') failed++
    else if (step.status === 'active' && !active) active = step
  }
  return { total: steps.length, done, failed, active }
}
