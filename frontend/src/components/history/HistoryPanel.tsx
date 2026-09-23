import { useEffect, useState } from 'react'
import { cn } from '@/lib/cn'
import { useHistoryState } from '@/state/HistoryProvider'
import { useQueryState } from '@/state/QueryProvider'
import { formatCompact, formatDuration, formatRelativeTime, truncate } from '@/lib/format'
import { Panel } from '@/components/ui/Panel'
import { Button, IconButton } from '@/components/ui/Button'
import { HistoryIcon, RefreshIcon, TrashIcon } from '@/components/ui/Icons'
import type { QueryHistoryEntry } from '@/types/query'

/**
 * Past queries.
 *
 * Metadata only, stored in localStorage — the GeoJSON never is. Within a
 * session a click puts the previous layers straight back on the map from the
 * in-memory result cache; after a reload the geometry is gone, so the row
 * offers to load the text into the composer and run it again instead of
 * pretending it still has the data.
 */
export function HistoryPanel() {
  const { entries, clear, remove } = useHistoryState()
  const { restoreEntry, fillDraft, query } = useQueryState()
  const [unavailableId, setUnavailableId] = useState<string | null>(null)

  // Clear the "not cached" note once the user moves on.
  useEffect(() => {
    if (!unavailableId) return
    const timer = window.setTimeout(() => setUnavailableId(null), 4000)
    return () => window.clearTimeout(timer)
  }, [unavailableId])

  function handleOpen(entry: QueryHistoryEntry) {
    const restored = restoreEntry(entry)
    if (restored) {
      setUnavailableId(null)
      return
    }
    setUnavailableId(entry.id)
    fillDraft(entry.query)
  }

  return (
    <Panel
      title="History"
      icon={<HistoryIcon size={14} />}
      className="min-h-0 flex-1"
      scroll
      flush
      actions={
        entries.length > 0 ? (
          <>
            <span className="font-mono text-[10px] tabular-nums text-ink-3">{entries.length}</span>
            <IconButton label="Clear history" variant="default" onClick={clear}>
              <TrashIcon size={13} />
            </IconButton>
          </>
        ) : null
      }
    >
      {entries.length === 0 ? (
        <p className="p-3 text-[12px] leading-relaxed text-ink-3">
          Finished queries are listed here, stored in this browser only. Nothing is sent anywhere.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {entries.map((entry) => {
            const isCurrent = query.run.query === entry.query
            const layersGone = unavailableId === entry.id
            return (
              <li
                key={entry.id}
                className={cn('group relative', isCurrent && 'bg-accent-soft/28')}
              >
                <button
                  type="button"
                  onClick={() => handleOpen(entry)}
                  className="block w-full px-3 py-2 pr-9 text-left hover:bg-panel-muted"
                  title={
                    layersGone
                      ? 'Result layers are no longer cached'
                      : 'Restore this query and its result layers'
                  }
                >
                  <span className="flex items-start gap-2">
                    <StatusDot status={entry.status} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12px] leading-snug text-ink">
                        {truncate(entry.query, 96)}
                      </span>

                      <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[10px] tabular-nums text-ink-3">
                        <span>{formatRelativeTime(entry.timestamp)}</span>
                        <span aria-hidden="true">·</span>
                        <span className="text-ink-2">{statusLabel(entry.status)}</span>
                        {entry.resultCount != null ? (
                          <>
                            <span aria-hidden="true">·</span>
                            <span>{formatCompact(entry.resultCount)} features</span>
                          </>
                        ) : null}
                        {entry.durationMs != null ? (
                          <>
                            <span aria-hidden="true">·</span>
                            <span>{formatDuration(entry.durationMs)}</span>
                          </>
                        ) : null}
                      </span>

                      {entry.dataset ? (
                        <span className="mt-0.5 block truncate text-[10px] text-ink-3">
                          {entry.dataset}
                        </span>
                      ) : null}

                      {layersGone ? (
                        <span className="mt-1 flex items-center gap-1 text-[10px] text-ink-2">
                          <RefreshIcon size={11} />
                          Layers expired from memory — text loaded, press Run to recompute
                        </span>
                      ) : null}
                    </span>
                  </span>
                </button>

                <div className="absolute right-1.5 top-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                  <IconButton
                    label="Remove from history"
                    variant="default"
                    onClick={() => remove(entry.id)}
                  >
                    <TrashIcon size={12} />
                  </IconButton>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {entries.length > 0 ? (
        <div className="border-t border-line p-2">
          <Button
            size="sm"
            variant="ghost"
            fullWidth
            icon={<RefreshIcon size={12} />}
            onClick={() => {
              const [latest] = entries
              if (latest) fillDraft(latest.query)
            }}
          >
            Re-run most recent
          </Button>
        </div>
      ) : null}
    </Panel>
  )
}

function StatusDot({ status }: { status: QueryHistoryEntry['status'] }) {
  const tone =
    status === 'completed'
      ? 'bg-good'
      : status === 'failed'
        ? 'bg-critical'
        : 'bg-ink-3'
  return (
    <span className="mt-[6px] flex shrink-0 items-center">
      <span className={cn('size-1.5 rounded-full', tone)} aria-hidden="true" />
    </span>
  )
}

function statusLabel(status: QueryHistoryEntry['status']): string {
  if (status === 'completed') return 'completed'
  if (status === 'failed') return 'failed'
  return 'cancelled'
}
