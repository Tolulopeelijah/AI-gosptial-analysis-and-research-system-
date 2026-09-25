import type { AgentEvent, GeoQueryError, ProcessingStep, RunStatus } from './agent'
import type {
  GeographicResult,
  KnowledgeReference,
  QueryContext,
  ResearchPaper,
  TableResult,
} from './geospatial'

/** How a query should be handled: conversation, full pipeline, map-first, or raw data. */
export type QueryMode = 'chat' | 'research' | 'spatial' | 'data'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

/** One conversational turn, kept client-side for the chat thread. */
export interface ChatTurn {
  query: string
  answer: string
  references?: KnowledgeReference[]
  dataset?: string
  count?: number
  errorCode?: GeoQueryError['code']
}

/**
 * Request/response contract for the geospatial query service.
 *
 * `src/services/geospatialApi.ts` is the only module that knows how these are
 * transported (HTTP/SSE against the agent backend).
 */
export interface QueryRequest {
  query: string
  context?: QueryContext
  mode?: QueryMode
  history?: ChatMessage[]
  /** Research aims/objectives (research mode). */
  aims?: string
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
  /** Tabular outputs, for display and download. */
  tables?: TableResult[]
  /** Research-paper report (research mode). */
  paper?: ResearchPaper
}

/** Options accepted by `submitGeospatialQuery`. */
export interface SubmitOptions {
  signal?: AbortSignal
  /** Receives every intermediate agent event as it is emitted. */
  onEvent?: (event: AgentEvent) => void
  /** Extra context (map bounds, a future drawn selection, …). */
  context?: QueryContext
  /** Handling mode; defaults to `research`. */
  mode?: QueryMode
  /** Recent conversation turns (used in `chat` mode for follow-ups). */
  history?: ChatMessage[]
  /** Research aims/objectives (used in `research` mode). */
  aims?: string
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
  /** Tabular outputs from the last run. */
  tables?: TableResult[]
  /** Research-paper report from the last run (research mode). */
  paper?: ResearchPaper
  /** Message lines that are not steps, e.g. the planner's narration. */
  messages: string[]
  startedAt?: number
  finishedAt?: number
}
