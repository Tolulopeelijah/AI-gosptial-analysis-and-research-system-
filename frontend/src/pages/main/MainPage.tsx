import { useState } from 'react'
import { AppHeader } from '@/components/layout/AppHeader'
import { ActivityRail } from '@/components/layout/ActivityRail'
import { ModeSelector } from '@/components/query/ModeSelector'
import { QueryPanel } from '@/components/query/QueryPanel'
import { ChatPanel } from '@/components/query/ChatPanel'
import { ResearchBrief } from '@/components/query/ResearchBrief'
import { ProcessingPanel } from '@/components/processing/ProcessingPanel'
import { ResultsPanel } from '@/components/results/ResultsPanel'
import { PaperPanel } from '@/components/results/PaperPanel'
import { TablesSection } from '@/components/results/TablesSection'
import { MapCanvas } from '@/components/map/MapCanvas'
import { IconButton } from '@/components/ui/Button'
import {
  ChevronDownIcon,
  ChevronRightIcon,
  MenuIcon,
} from '@/components/ui/Icons'
import { useQueryState } from '@/state/QueryProvider'
import { cn } from '@/lib/cn'

/**
 * The workbench.
 *
 * A slim activity rail at the extreme left (history, upload, and later
 * settings), then two regions, each with one job:
 *   left  — ask (always visible) with progress directly below it, or the
 *           chat thread in chat mode; takes the freed room since it is the
 *           primary surface for casual users
 *   right — a deliberately narrow but tall pane: the map on top with the
 *           agent's explanation and data below it. An edge toggle hides the
 *           whole pane (unveiled again with the hamburger); the map and each
 *           result panel also collapse individually into their headers.
 *
 * On narrow screens the regions stack in that order, so the prompt is never
 * covered by the map.
 */
export function MainPage() {
  const { mode, query } = useQueryState()
  const showPaper =
    mode === 'research' && !query.isRunning && query.run.status === 'completed' && !!query.run.paper
  const [mapOpen, setMapOpen] = useState(true)
  const [paneOpen, setPaneOpen] = useState(true)

  return (
    <div className="flex h-dvh min-h-0 flex-col bg-canvas text-ink">
      <AppHeader />

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2 lg:flex-row lg:overflow-hidden">
        <ActivityRail />
        <aside
          aria-label="Query workspace"
          className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 lg:overflow-y-auto"
        >
          <ModeSelector />

          {mode === 'chat' ? (
            <ChatPanel />
          ) : (
            <>
              {mode === 'research' ? <ResearchBrief /> : null}
              <QueryPanel />
              <ProcessingPanel />
            </>
          )}
        </aside>

        {paneOpen ? (
          <aside
            aria-label="Map and answer"
            className="flex min-h-0 flex-col gap-2 lg:w-[560px] lg:shrink-0 lg:overflow-hidden xl:w-[640px]"
          >
            <section
              aria-label="Map"
              className={cn(
                'flex shrink-0 flex-col border border-line bg-panel',
                mapOpen && 'h-[460px] lg:h-[57%] lg:min-h-[320px]',
                mapOpen && mode === 'spatial' && 'lg:h-[66%]',
              )}
            >
              <div className="flex h-9 shrink-0 items-center justify-between gap-2 px-3">
                <button
                  type="button"
                  onClick={() => setMapOpen((value) => !value)}
                  aria-expanded={mapOpen}
                  title={mapOpen ? 'Collapse map' : 'Expand map'}
                  className="flex min-w-0 items-center gap-1.5 text-left"
                >
                  <span className="shrink-0 text-ink-3">
                    {mapOpen ? <ChevronDownIcon size={13} /> : <ChevronRightIcon size={13} />}
                  </span>
                  <span className="truncate text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-2">
                    Map
                  </span>
                </button>
                <IconButton
                  label="Hide map and results"
                  variant="ghost"
                  onClick={() => setPaneOpen(false)}
                  title="Hide map and results"
                >
                  <ChevronRightIcon size={14} />
                </IconButton>
              </div>
              {mapOpen ? (
                <div className="min-h-0 flex-1 border-t border-line">
                  <MapCanvas />
                </div>
              ) : null}
            </section>

            <div
              aria-label="Answer"
              className="flex min-h-0 flex-1 flex-col gap-2 lg:overflow-y-auto"
            >
              {showPaper ? <PaperPanel /> : <ResultsPanel />}
              {mode === 'data' ? <TablesSection /> : null}
            </div>
          </aside>
        ) : (
          <div
            aria-label="Map and results hidden"
            className="flex shrink-0 flex-row items-center gap-2 border border-line bg-panel px-2 py-1.5 lg:w-9 lg:flex-col lg:px-0 lg:py-2"
          >
            <IconButton
              label="Show map and results"
              variant="default"
              onClick={() => setPaneOpen(true)}
              title="Show map and results"
            >
              <MenuIcon />
            </IconButton>
            <span className="text-[11px] text-ink-3 lg:hidden">Map &amp; results hidden</span>
          </div>
        )}
      </div>
    </div>
  )
}
