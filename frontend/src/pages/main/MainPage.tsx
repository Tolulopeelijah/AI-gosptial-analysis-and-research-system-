import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/cn'
import { AppHeader } from '@/components/layout/AppHeader'
import { QueryPanel } from '@/components/query/QueryPanel'
import { ProcessingPanel } from '@/components/processing/ProcessingPanel'
import { HistoryPanel } from '@/components/history/HistoryPanel'
import { ResultsPanel } from '@/components/results/ResultsPanel'
import { MapCanvas } from '@/components/map/MapCanvas'
import { useQueryState } from '@/state/QueryProvider'
import { useHistoryState } from '@/state/HistoryProvider'

type RailTab = 'ask' | 'progress' | 'history'

const RAIL_TABS: Array<{ id: RailTab; label: string }> = [
  { id: 'ask', label: 'Ask' },
  { id: 'progress', label: 'Progress' },
  { id: 'history', label: 'History' },
]

/**
 * The workbench.
 *
 * Two regions, each with one job:
 *   left rail  — one task at a time (ask, follow progress, revisit history)
 *   centre     — the map, which is the answer, with the result data beneath it
 *
 * Secondary panels live behind the rail tabs so the initial screen is only
 * the composer and the map. The rail is a fixed measure so the map keeps a
 * predictable share of the window.
 */
export function MainPage() {
  const [tab, setTab] = useState<RailTab>('ask')
  const { query } = useQueryState()
  const { entries } = useHistoryState()
  const running = query.isRunning
  const prevRunning = useRef(running)

  // When a run starts, bring the progress panel forward exactly once.
  useEffect(() => {
    if (running && !prevRunning.current) setTab('progress')
    prevRunning.current = running
  }, [running])

  return (
    <div className="flex h-dvh min-h-0 flex-col bg-canvas text-ink">
      <AppHeader />

      <div className="flex min-h-0 flex-1 flex-col gap-2 p-2 lg:flex-row">
        <aside
          aria-label="Query workspace"
          className="flex min-h-0 shrink-0 flex-col gap-2 lg:w-[376px] xl:w-[412px]"
        >
          <nav
            aria-label="Workspace views"
            className="flex shrink-0 items-center gap-0.5 border border-line bg-panel p-0.5"
          >
            {RAIL_TABS.map((entry) => (
              <button
                key={entry.id}
                type="button"
                onClick={() => setTab(entry.id)}
                aria-pressed={tab === entry.id}
                className={cn(
                  'flex flex-1 items-center justify-center gap-1.5 rounded-[2px] px-2 py-1.5 text-[12px]',
                  tab === entry.id
                    ? 'bg-panel-muted font-medium text-ink'
                    : 'text-ink-2 hover:text-ink',
                )}
              >
                {entry.label}
                {entry.id === 'progress' && running ? (
                  <span
                    className="size-1.5 animate-pulse rounded-full bg-accent"
                    aria-label="query running"
                  />
                ) : null}
                {entry.id === 'history' && entries.length > 0 ? (
                  <span className="font-mono text-[10px] text-ink-3">{entries.length}</span>
                ) : null}
              </button>
            ))}
          </nav>

          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            {tab === 'ask' ? <QueryPanel /> : null}
            {tab === 'progress' ? <ProcessingPanel /> : null}
            {tab === 'history' ? <HistoryPanel /> : null}
          </div>
        </aside>

        <main className="flex min-h-0 flex-1 flex-col gap-2">
          <div className="min-h-[320px] flex-1 border border-line">
            <MapCanvas />
          </div>
          <ResultsPanel />
        </main>
      </div>
    </div>
  )
}
