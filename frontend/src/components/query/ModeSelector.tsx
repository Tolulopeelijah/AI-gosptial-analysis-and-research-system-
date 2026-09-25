import { cn } from '@/lib/cn'
import { useQueryState } from '@/state/QueryProvider'
import type { QueryMode } from '@/types/query'

const MODES: Array<{ id: QueryMode; label: string; hint: string }> = [
  { id: 'chat', label: 'Chat', hint: 'Conversational Q&A with follow-ups' },
  { id: 'research', label: 'Research', hint: 'Full workflow: plan, execute, explain' },
  { id: 'spatial', label: 'Spatial', hint: 'Map-first spatial analysis' },
  { id: 'data', label: 'Data', hint: 'Raw tables and layers for download' },
]

/**
 * The four handling modes.
 *
 * Always visible at the top of the rail: the mode changes what the backend
 * does with a query (conversation vs. full pipeline vs. raw retrieval) and
 * how the workspace lays out around the answer.
 */
export function ModeSelector({ disabled = false }: { disabled?: boolean }) {
  const { mode, setMode } = useQueryState()

  return (
    <div
      role="tablist"
      aria-label="Query mode"
      className="grid shrink-0 grid-cols-4 gap-0.5 border border-line bg-panel p-0.5"
    >
      {MODES.map((entry) => (
        <button
          key={entry.id}
          type="button"
          role="tab"
          aria-selected={mode === entry.id}
          title={entry.hint}
          disabled={disabled}
          onClick={() => setMode(entry.id)}
          className={cn(
            'rounded-[2px] px-1 py-1.5 text-[12px] font-medium disabled:cursor-not-allowed',
            mode === entry.id
              ? 'bg-accent text-white shadow-sm'
              : 'text-ink-2 hover:bg-panel-muted hover:text-ink disabled:hover:text-ink-2',
          )}
        >
          {entry.label}
        </button>
      ))}
    </div>
  )
}
