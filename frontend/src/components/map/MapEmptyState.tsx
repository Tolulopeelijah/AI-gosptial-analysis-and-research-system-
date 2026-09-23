import { EXAMPLE_QUERIES } from '@/data/scenarios'
import { useQueryState } from '@/state/QueryProvider'
import { AgentIcon } from '@/components/ui/Icons'

/**
 * The intentional empty state.
 *
 * Shown before anything has been asked. It sits over the live map (which stays
 * pannable and zoomable underneath) and states what the surface is for, in the
 * tool's own vocabulary — no hero copy, no illustration.
 */
export function MapEmptyState() {
  const { fillDraft } = useQueryState()
  const suggestions = EXAMPLE_QUERIES.filter((example) =>
    ['ex-intersect', 'ex-buffer', 'ex-maumee', 'ex-combined'].includes(example.id),
  )

  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
      <div className="pointer-events-auto w-full max-w-md rounded-[3px] border border-line-strong bg-panel/96 px-5 py-4 shadow-[0_6px_24px_rgb(11_11_11/0.10)] backdrop-blur-[2px]">
        <div className="flex items-center gap-2 text-ink-2">
          <AgentIcon size={15} />
          <h2 className="text-[13px] font-semibold text-ink">
            Ask a question about the geographic data
          </h2>
        </div>
        <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">
          The agent resolves the request into datasets and GIS operations — attribute filters,
          distance buffers, boundary intersections — then draws the result here.
        </p>

        <div className="mt-3 border-t border-line pt-3">
          <div className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
            Try
          </div>
          <ul className="mt-1.5 space-y-1">
            {suggestions.map((example) => (
              <li key={example.id}>
                <button
                  type="button"
                  onClick={() => fillDraft(example.text)}
                  className="w-full rounded-[2px] border border-transparent px-2 py-1 text-left text-[12px] text-ink-2 hover:border-line hover:bg-panel-muted hover:text-ink"
                >
                  <span className="text-ink-3">›</span> {example.text}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
