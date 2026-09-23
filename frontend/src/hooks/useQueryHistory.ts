import { useCallback, useEffect, useMemo, useState } from 'react'
import type { QueryHistoryEntry, QueryHistoryStatus } from '@/types/query'
import type { GeoQueryError } from '@/types/agent'

/**
 * Query history, persisted to localStorage.
 *
 * Only metadata is stored — never the GeoJSON. A single county result can be
 * megabytes, and localStorage caps out around 5 MB per origin. Restoring a
 * previous result layer is handled in-memory by `useResultCache` (see
 * `useGeospatialQuery`), so within a session a history entry can put its
 * features back on the map, and after a reload it restores the query text and
 * offers a re-run.
 */

const STORAGE_KEY = 'geoscope.history.v1'
const MAX_ENTRIES = 30

function isHistoryEntry(value: unknown): value is QueryHistoryEntry {
  if (!value || typeof value !== 'object') return false
  const entry = value as Partial<QueryHistoryEntry>
  return (
    typeof entry.id === 'string' &&
    typeof entry.query === 'string' &&
    typeof entry.timestamp === 'number' &&
    typeof entry.status === 'string'
  )
}

function readStoredHistory(): QueryHistoryEntry[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(isHistoryEntry)
      .sort((a, b) => b.timestamp - a.timestamp)
      .slice(0, MAX_ENTRIES)
  } catch {
    // Corrupt or unavailable storage (private mode, quota) must not break the app.
    return []
  }
}

function writeStoredHistory(entries: QueryHistoryEntry[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
  } catch {
    // Ignore quota/security errors: history is a convenience, not state of record.
  }
}

let entrySequence = 0
function createEntryId(): string {
  entrySequence += 1
  return `h_${Date.now().toString(36)}_${entrySequence}`
}

export interface RecordQueryInput {
  queryId: string
  query: string
  status: QueryHistoryStatus
  resultCount?: number
  explanation?: string
  dataset?: string
  durationMs?: number
  errorCode?: GeoQueryError['code']
}

export interface UseQueryHistoryResult {
  entries: QueryHistoryEntry[]
  record: (input: RecordQueryInput) => void
  remove: (id: string) => void
  clear: () => void
}

export function useQueryHistory(): UseQueryHistoryResult {
  const [entries, setEntries] = useState<QueryHistoryEntry[]>(() =>
    typeof window === 'undefined' ? [] : readStoredHistory(),
  )

  useEffect(() => {
    writeStoredHistory(entries)
  }, [entries])

  // Keep multiple tabs in step.
  useEffect(() => {
    function onStorage(event: StorageEvent) {
      if (event.key !== STORAGE_KEY) return
      setEntries(readStoredHistory())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const record = useCallback((input: RecordQueryInput) => {
    const entry: QueryHistoryEntry = {
      id: createEntryId(),
      runId: input.queryId,
      query: input.query,
      timestamp: Date.now(),
      status: input.status,
      resultCount: input.resultCount,
      explanation: input.explanation,
      dataset: input.dataset,
      durationMs: input.durationMs,
      errorCode: input.errorCode,
    }
    setEntries((current) => {
      // Collapse an immediate repeat of the same query into one row.
      const withoutDuplicate = current.filter(
        (existing) => existing.query !== input.query || existing.status !== input.status,
      )
      return [entry, ...withoutDuplicate].slice(0, MAX_ENTRIES)
    })
  }, [])

  const remove = useCallback((id: string) => {
    setEntries((current) => current.filter((entry) => entry.id !== id))
  }, [])

  const clear = useCallback(() => setEntries([]), [])

  return useMemo(
    () => ({ entries, record, remove, clear }),
    [entries, record, remove, clear],
  )
}
