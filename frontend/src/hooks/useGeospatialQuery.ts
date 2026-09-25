import { useCallback, useMemo, useReducer, useRef } from 'react'
import { applyAgentEvent } from '@/services/agentSteps'
import { submitGeospatialQuery } from '@/services/geospatialApi'
import type { AgentEvent, GeoQueryError } from '@/types/agent'
import type { GeographicResult, QueryContext, TableResult } from '@/types/geospatial'
import type {
  ChatMessage,
  QueryHistoryStatus,
  QueryMode,
  QueryResponse,
  QueryRun,
} from '@/types/query'

/**
 * Owns the lifecycle of a single query run.
 *
 * Deliberately narrow: it holds the current run (status, steps, results,
 * explanation, error) and nothing else. History lives in `useQueryHistory`,
 * map state lives in the map context, and the API lives behind
 * `services/geospatialApi`.
 */

const EMPTY_RUN: QueryRun = {
  queryId: null,
  query: '',
  status: 'idle',
  steps: [],
  results: [],
  messages: [],
}

type Action =
  | { type: 'submit'; queryId: string; query: string; at: number }
  | { type: 'event'; event: AgentEvent }
  | { type: 'settle'; response: QueryResponse; at: number }
  | { type: 'fail'; error: GeoQueryError; at: number }
  | { type: 'reset' }
  | { type: 'restore'; run: Partial<QueryRun> & { query: string } }

function reducer(state: QueryRun, action: Action): QueryRun {
  switch (action.type) {
    case 'submit':
      return {
        ...EMPTY_RUN,
        queryId: action.queryId,
        query: action.query,
        status: 'submitted',
        startedAt: action.at,
      }

    case 'event': {
      const { event } = action
      const steps = applyAgentEvent(state.steps, event)
      const next: QueryRun = { ...state, steps }

      if (event.type === 'query_received' && event.queryId) next.queryId = event.queryId
      if (state.status === 'submitted') next.status = 'processing'

      switch (event.type) {
        case 'planning':
          next.messages = [...state.messages, event.message]
          break
        case 'result':
          next.results = [...state.results, event.data]
          break
        case 'error':
          next.error = {
            code: event.code,
            message: event.message,
            detail: event.detail,
            hint: event.hint,
          }
          next.status = 'failed'
          next.finishedAt = Date.now()
          break
        case 'completed':
          next.explanation = event.explanation ?? state.explanation
          next.dataset = event.dataset ?? state.dataset
          next.count = event.count ?? state.count
          next.references = event.references ?? state.references
          next.tables = event.tables ?? state.tables
          break
        default:
          break
      }
      return next
    }

    case 'settle': {
      const { response } = action
      if (response.status === 'failed') {
        return {
          ...state,
          status: 'failed',
          error: response.error ?? state.error ?? {
            code: 'query_failed',
            message: response.message ?? 'The query failed.',
          },
          finishedAt: action.at,
        }
      }
      return {
        ...state,
        status: 'completed',
        // A streaming backend already delivered results via `result` events;
        // a single-response backend delivers them here instead.
        results: response.results?.length ? response.results : state.results,
        explanation: response.explanation ?? state.explanation,
        dataset: response.dataset ?? state.dataset,
        count: response.count ?? state.count,
        references: response.references ?? state.references,
        tables: response.tables ?? state.tables,
        error: undefined,
        finishedAt: action.at,
      }
    }

    case 'fail':
      return {
        ...state,
        status: 'failed',
        error: action.error,
        finishedAt: action.at,
      }

    case 'restore': {
      // The payload is partial (a history entry carries no steps or messages),
      // so the required fields are filled explicitly rather than relying on the
      // spread to produce a complete `QueryRun`.
      const previous = action.run
      return {
        ...EMPTY_RUN,
        ...previous,
        queryId: previous.queryId ?? null,
        query: previous.query,
        results: previous.results ?? [],
        steps: previous.steps ?? [],
        messages: previous.messages ?? [],
      }
    }

    case 'reset':
      return EMPTY_RUN

    default:
      return state
  }
}

export interface SubmitOutcome {
  queryId: string
  status: QueryHistoryStatus
  resultCount?: number
  explanation?: string
  dataset?: string
  durationMs?: number
  errorCode?: GeoQueryError['code']
  references?: QueryResponse['references']
  tables?: TableResult[]
}

export interface UseGeospatialQueryResult {
  run: QueryRun
  isRunning: boolean
  submit: (query: string, context?: QueryContext, opts?: SubmitRequestOptions) => void
  cancel: () => void
  reset: () => void
  /** Restores a previous run's results onto the map without re-querying. */
  restore: (run: Partial<QueryRun> & { query: string }) => void
}

export interface SubmitRequestOptions {
  mode?: QueryMode
  history?: ChatMessage[]
}

export interface UseGeospatialQueryOptions {
  /** Called once when a run reaches a terminal state. */
  onSettled?: (query: string, outcome: SubmitOutcome) => void
}

export function useGeospatialQuery(options: UseGeospatialQueryOptions = {}): UseGeospatialQueryResult {
  const [run, dispatch] = useReducer(reducer, EMPTY_RUN)
  const handleRef = useRef<ReturnType<typeof submitGeospatialQuery> | null>(null)
  const settledRef = useRef<Set<string>>(new Set())
  const onSettledRef = useRef(options.onSettled)
  onSettledRef.current = options.onSettled

  const isRunning = run.status === 'submitted' || run.status === 'processing'

  const submit = useCallback((query: string, context?: QueryContext, opts?: SubmitRequestOptions) => {
    const trimmed = query.trim()
    if (!trimmed) return

    // Supersede any run still in flight.
    handleRef.current?.cancel()

    const startedAt = Date.now()
    const handle = submitGeospatialQuery(trimmed, {
      context,
      mode: opts?.mode,
      history: opts?.history,
      onEvent: (event) => dispatch({ type: 'event', event }),
    })
    handleRef.current = handle
    dispatch({ type: 'submit', queryId: handle.queryId, query: trimmed, at: startedAt })

    const settle = (outcome: SubmitOutcome) => {
      if (settledRef.current.has(handle.queryId)) return
      settledRef.current.add(handle.queryId)
      onSettledRef.current?.(trimmed, outcome)
    }

    handle.response
      .then((response) => {
        dispatch({ type: 'settle', response, at: Date.now() })
        settle({
          queryId: handle.queryId,
          status: response.status === 'failed' ? 'failed' : 'completed',
          resultCount:
            response.count ??
            response.results?.reduce((sum, result) => sum + (result.metadata?.count ?? 0), 0),
          explanation: response.explanation,
          dataset: response.dataset,
          durationMs: response.timingMs ?? Date.now() - startedAt,
          errorCode: response.error?.code,
          references: response.references,
          tables: response.tables,
        })
      })
      .catch((error: unknown) => {
        const aborted = error instanceof Error && error.name === 'AbortError'
        if (aborted) {
          dispatch({
            type: 'fail',
            error: {
              code: 'aborted',
              message: 'Query cancelled.',
              detail: 'The run was stopped before it finished.',
            },
            at: Date.now(),
          })
          settle({ queryId: handle.queryId, status: 'cancelled', durationMs: Date.now() - startedAt })
          return
        }
        const detail = error instanceof Error ? error.message : String(error)
        dispatch({
          type: 'fail',
          error: {
            code: 'backend_unavailable',
            message: 'The geospatial service could not be reached.',
            detail,
            hint: 'Check that the backend is running, then try again.',
          },
          at: Date.now(),
        })
        settle({
          queryId: handle.queryId,
          status: 'failed',
          durationMs: Date.now() - startedAt,
          errorCode: 'backend_unavailable',
        })
      })
  }, [])

  const cancel = useCallback(() => {
    handleRef.current?.cancel()
    handleRef.current = null
  }, [])

  const reset = useCallback(() => {
    handleRef.current?.cancel()
    handleRef.current = null
    dispatch({ type: 'reset' })
  }, [])

  const restore = useCallback((previous: Partial<QueryRun> & { query: string }) => {
    handleRef.current?.cancel()
    handleRef.current = null
    dispatch({ type: 'restore', run: previous })
  }, [])

  return useMemo(
    () => ({ run, isRunning, submit, cancel, reset, restore }),
    [run, isRunning, submit, cancel, reset, restore],
  )
}

/** Results cache used to restore a previous run's layers without re-querying. */
export function useResultCache(maxEntries = 6) {
  const cacheRef = useRef(new Map<string, GeographicResult[]>())
  return useMemo(
    () => ({
      put(queryId: string, results: GeographicResult[]) {
        const cache = cacheRef.current
        cache.delete(queryId)
        cache.set(queryId, results)
        while (cache.size > maxEntries) {
          const oldest = cache.keys().next().value
          if (oldest == null) break
          cache.delete(oldest)
        }
      },
      get(queryId: string): GeographicResult[] | undefined {
        return cacheRef.current.get(queryId)
      },
    }),
    [maxEntries],
  )
}
