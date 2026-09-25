import type {
  GeographicResult,
  KnowledgeReference,
  ResearchPaper,
  TableResult,
} from './geospatial'

/**
 * Events the orchestration/agent layer emits while a query runs.
 *
 * This union is the contract the UI is written against. The agent backend
 * emits these objects over SSE and nothing in the UI layer has to change.
 */
export type AgentEvent =
  | { type: 'query_received'; queryId: string }
  | {
      type: 'planning'
      message: string
      /** Human-readable task names, for narration. */
      tasks?: string[]
      /**
       * The tasks the planner intends to run, so the UI can show the whole plan
       * up front with later steps pending. Optional: a backend that only streams
       * tool calls as they happen still works — the steps get appended instead.
       */
      plan?: Array<{ id: string; tool: string; label: string }>
    }
  | {
      type: 'tool_call'
      tool: string
      status: 'started' | 'completed' | 'failed'
      /** Short human-readable result of the call, e.g. "254 counties loaded". */
      message?: string
      /** Machine-level detail, shown behind a disclosure. */
      detail?: string
      durationMs?: number
    }
  | { type: 'result'; data: GeographicResult }
  | {
      type: 'completed'
      explanation?: string
      dataset?: string
      count?: number
      references?: KnowledgeReference[]
      tables?: TableResult[]
      paper?: ResearchPaper
    }
  | { type: 'paper'; paper: ResearchPaper }
  | { type: 'error'; code: GeoErrorCode; message: string; detail?: string; hint?: string }

export type GeoErrorCode =
  | 'backend_unavailable'
  | 'query_failed'
  | 'no_results'
  | 'invalid_geographic_query'
  | 'data_unavailable'
  | 'processing_error'
  | 'timeout'
  | 'aborted'

export interface GeoQueryError {
  code: GeoErrorCode
  message: string
  /** The underlying technical message, for the disclosure. */
  detail?: string
  /** What the user could try instead. */
  hint?: string
}

export type RunStatus = 'idle' | 'submitted' | 'processing' | 'completed' | 'failed'

export type StepStatus = 'pending' | 'active' | 'done' | 'failed'

/** Groups steps so the panel can pick an icon and a section heading. */
export type StepKind = 'understand' | 'dataset' | 'plan' | 'tool' | 'result' | 'finalize'

/**
 * A single line in the processing panel.
 *
 * Steps are derived from `AgentEvent`s by `src/services/agentSteps.ts`, so the
 * panel itself only ever renders a list — it knows nothing about event shapes.
 */
export interface ProcessingStep {
  id: string
  label: string
  status: StepStatus
  kind: StepKind
  detail?: string
  /** Tool name for `tool` steps, kept for the technical disclosure. */
  tool?: string
  durationMs?: number
}
