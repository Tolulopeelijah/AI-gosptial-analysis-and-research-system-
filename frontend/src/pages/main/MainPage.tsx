import { AppHeader } from '@/components/layout/AppHeader'
import { ModeSelector } from '@/components/query/ModeSelector'
import { QueryPanel } from '@/components/query/QueryPanel'
import { ChatPanel } from '@/components/query/ChatPanel'
import { ResearchBrief } from '@/components/query/ResearchBrief'
import { DataUpload } from '@/components/query/DataUpload'
import { ProcessingPanel } from '@/components/processing/ProcessingPanel'
import { ResultsPanel } from '@/components/results/ResultsPanel'
import { PaperPanel } from '@/components/results/PaperPanel'
import { TablesSection } from '@/components/results/TablesSection'
import { MapCanvas } from '@/components/map/MapCanvas'
import { useQueryState } from '@/state/QueryProvider'
import { cn } from '@/lib/cn'

/**
 * The workbench.
 *
 * Three regions on wide screens, each with one job:
 *   left rail  — ask (always visible) with progress directly below it,
 *                or the chat thread in chat mode
 *   centre     — the agent's explanation and data, given the most room
 *   right      — a deliberately narrow map; past prompts live behind the
 *                hamburger menu in the header
 *
 * On narrow screens the regions stack in that order, so the prompt is never
 * covered by the map.
 */
export function MainPage() {
  const { mode, query } = useQueryState()
  const showPaper =
    mode === 'research' && !query.isRunning && query.run.status === 'completed' && !!query.run.paper

  return (
    <div className="flex h-dvh min-h-0 flex-col bg-canvas text-ink">
      <AppHeader />

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2 lg:flex-row lg:overflow-hidden">
        <aside
          aria-label="Query workspace"
          className="flex shrink-0 flex-col gap-2 lg:min-h-0 lg:w-[380px] lg:overflow-y-auto xl:w-[410px]"
        >
          <ModeSelector />

          {mode === 'chat' ? (
            <ChatPanel />
          ) : (
            <>
              {mode === 'research' ? <ResearchBrief /> : null}
              <QueryPanel />
              {mode === 'data' ? <DataUpload /> : null}
              <ProcessingPanel />
            </>
          )}
        </aside>

        <main
          aria-label="Answer"
          className="flex min-h-0 flex-1 flex-col gap-2 lg:overflow-y-auto"
        >
          {showPaper ? <PaperPanel /> : <ResultsPanel />}
          {mode === 'data' ? <TablesSection /> : null}
        </main>

        <section
          aria-label="Map"
          className={cn(
            'h-[320px] shrink-0 border border-line lg:h-auto',
            mode === 'spatial' && 'lg:w-[480px] xl:w-[560px]',
            mode !== 'spatial' && 'lg:w-[340px] xl:w-[400px]',
          )}
        >
          <MapCanvas />
        </section>
      </div>
    </div>
  )
}
