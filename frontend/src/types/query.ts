import type { AgentEvent, GeoQueryError, ProcessingStep, RunStatus } from './agent'
import type { GeographicResult, KnowledgeReference, QueryContext } from './geospatial'

/**
 * Request/response contract for the geospatial query service.
 *
 * `src/services/geospatialApi.ts` is the only module that knows how these are
 * transported (HTTP/SSE against the agent backend).
 */
export interface QueryRequest {
  query: string
  context?: QueryContext
}

export interface QueryResponse {
  queryId: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  message?: string
  explanation?: string
  results?: GeographicResult[]
  /** Dataset(s) that answered the query, for the results panel. */
  dataset?: string
  /** Feature count as reported by the backend (may exceed what is drawn). */
  count?: number
  error?: GeoQueryError
  timingMs?: number
  /** Knowledge sources behind the answer; refs match inline [S#] markers. */
  references?: KnowledgeReference[]
}

/** Options accepted by `submitGeospatialQuery`. */
export interface SubmitOptions {
  signal?: AbortSignal
  /** Receives every intermediate agent event as it is emitted. */
  onEvent?: (event: AgentEvent) => void
  /** Extra context (map bounds, a future drawn selection, …). */
  context?: QueryContext
}

export interface SubmitHandle {
  queryId: string
  /** Resolves with the terminal response; rejects only on transport failure. */
  response: Promise<QueryResponse>
  /** Ask the backend to stop work. */
  cancel: () => void
}

/** Connection state for the header indicator. */
export type ConnectionStatus = 'unknown' | 'online' | 'offline' | 'checking'

export type QueryHistoryStatus = 'completed' | 'failed' | 'cancelled'

export interface QueryHistoryEntry {
  id: string
  query: string
  /** Epoch milliseconds. */
  timestamp: number
  status: QueryHistoryStatus
  /** The run this entry came from; lets the session result cache be looked up. */
  runId?: string
  resultCount?: number
  explanation?: string
  dataset?: string
  durationMs?: number
  errorCode?: GeoQueryError['code']
}

/**
 * The live state of one query run.
 *
 * Kept deliberately flat and separate from history and map state so a run can
 * be reset without touching anything else.
 */
export interface QueryRun {
  queryId: string | null
  query: string
  status: RunStatus
  steps: ProcessingStep[]
  results: GeographicResult[]
  explanation?: string
  dataset?: string
  count?: number
  /** Set when the last run ended in failure. */
  error?: GeoQueryError
  /** Knowledge sources behind the last answer. */
  references?: KnowledgeReference[]
  /** Message lines that are not steps, e.g. the planner's narration. */
  messages: string[]
  startedAt?: number
  finishedAt?: number
}
