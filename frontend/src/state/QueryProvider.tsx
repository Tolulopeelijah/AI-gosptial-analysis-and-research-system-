import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  useGeospatialQuery,
  useResultCache,
  type UseGeospatialQueryResult,
} from '@/hooks/useGeospatialQuery'
import { useHistoryState } from './HistoryProvider'
import type {
  ChatMessage,
  ChatTurn,
  QueryHistoryEntry,
  QueryMode,
  QueryRun,
} from '@/types/query'

/**
 * The current query run, plus the wiring that records finished runs into
 * history and can restore a previous run's layers from the in-session cache.
 *
 * The composer's draft text lives here too, so an example query in the sidebar
 * and the map's empty state can both fill it without prop-drilling through the
 * layout.
 */
export interface QueryContextValue {
  query: UseGeospatialQueryResult
  /** Text currently in the composer. */
  draft: string
  setDraft: (value: string) => void
  /** Replaces the draft and asks the composer to take focus. */
  fillDraft: (value: string) => void
  /** Increments each time focus is requested, so the composer can react to it. */
  focusRequest: number
  /**
   * Puts a previous run's results back on the map.
   * Returns false when the layers are no longer cached (e.g. after a reload),
   * in which case the caller should offer a re-run instead.
   */
  restoreEntry: (entry: QueryHistoryEntry) => boolean
  /** Handling mode for the next query. */
  mode: QueryMode
  setMode: (mode: QueryMode) => void
  /** Conversational turns (chat mode only), oldest first. */
  chatTurns: ChatTurn[]
  /** History payload sent with chat follow-ups. */
  chatHistory: ChatMessage[]
  clearChat: () => void
}

const QueryContext = createContext<QueryContextValue | null>(null)

export function QueryProvider({ children }: { children: ReactNode }) {
  const history = useHistoryState()
  const resultCache = useResultCache()
  const { record } = history
  const [draft, setDraft] = useState('')
  const [focusRequest, setFocusRequest] = useState(0)
  const [mode, setMode] = useState<QueryMode>('research')
  const [chatTurns, setChatTurns] = useState<ChatTurn[]>([])
  const modeRef = useRef<QueryMode>('research')
  modeRef.current = mode

  const query = useGeospatialQuery({
    onSettled: (text, outcome) => {
      record({
        queryId: outcome.queryId,
        query: text,
        status: outcome.status,
        resultCount: outcome.resultCount,
        explanation: outcome.explanation,
        dataset: outcome.dataset,
        durationMs: outcome.durationMs,
        errorCode: outcome.errorCode,
      })
      if (modeRef.current === 'chat') {
        const answer =
          outcome.status === 'cancelled'
            ? 'Cancelled.'
            : outcome.status === 'failed'
              ? 'That failed — try rephrasing, or switch to research mode for the full pipeline.'
              : (outcome.explanation ?? 'Done.')
        setChatTurns((turns) => [
          ...turns,
          {
            query: text,
            answer,
            references: outcome.references,
            dataset: outcome.dataset,
            count: outcome.resultCount,
            errorCode: outcome.status === 'failed' ? outcome.errorCode : undefined,
          },
        ])
      }
    },
  })

  const { run, restore } = query
  const { queryId, results, status } = run

  // Cache results as they land so history clicks can restore them without a
  // network round-trip. Keyed by run id, capped, and never persisted.
  useEffect(() => {
    if (!queryId || results.length === 0) return
    if (status === 'submitted' || status === 'processing') return
    resultCache.put(queryId, results)
  }, [queryId, results, status, resultCache])

  const restoreEntry = useCallback(
    (entry: QueryHistoryEntry): boolean => {
      const cached = entry.runId ? resultCache.get(entry.runId) : undefined
      if (!cached || cached.length === 0) return false
      const restored: Partial<QueryRun> & { query: string } = {
        queryId: entry.runId ?? null,
        query: entry.query,
        status: entry.status === 'failed' ? 'failed' : 'completed',
        results: cached,
        explanation: entry.explanation,
        dataset: entry.dataset,
        count: entry.resultCount,
        steps: [],
        messages: [],
        startedAt: entry.timestamp,
        finishedAt: entry.timestamp + (entry.durationMs ?? 0),
      }
      restore(restored)
      return true
    },
    [restore, resultCache],
  )

  const fillDraft = useCallback((value: string) => {
    setDraft(value)
    setFocusRequest((current) => current + 1)
  }, [])

  const clearChat = useCallback(() => setChatTurns([]), [])

  const chatHistory = useMemo<ChatMessage[]>(
    () =>
      chatTurns.flatMap((turn): ChatMessage[] => [
        { role: 'user', content: turn.query },
        { role: 'assistant', content: turn.answer },
      ]),
    [chatTurns],
  )

  const value = useMemo<QueryContextValue>(
    () => ({
      query,
      restoreEntry,
      draft,
      setDraft,
      fillDraft,
      focusRequest,
      mode,
      setMode,
      chatTurns,
      chatHistory,
      clearChat,
    }),
    [query, restoreEntry, draft, fillDraft, focusRequest, mode, chatTurns, chatHistory, clearChat],
  )

  return <QueryContext.Provider value={value}>{children}</QueryContext.Provider>
}

export function useQueryState(): QueryContextValue {
  const value = useContext(QueryContext)
  if (!value) throw new Error('useQueryState must be used inside <QueryProvider>')
  return value
}
