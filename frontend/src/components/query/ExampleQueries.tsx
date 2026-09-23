import { useState } from 'react'
import { cn } from '@/lib/cn'
import {
  EXAMPLE_QUERIES,
  EXAMPLE_TIER_LABELS,
  EXAMPLE_TIER_ORDER,
  type ExampleTier,
} from '@/data/scenarios'
import { useQueryState } from '@/state/QueryProvider'
import { ChevronDownIcon } from '@/components/ui/Icons'

/**
 * Clickable example queries, grouped by how much reasoning each one demands.
 *
 * The grouping is the point: it shows the range the system is meant to cover,
 * from a single boundary lookup to a query that has to be decomposed into
 * several GIS operations and recombined.
 */
export function ExampleQueries({ disabled = false }: { disabled?: boolean }) {
  const { fillDraft } = useQueryState()
  const [openTier, setOpenTier] = useState<ExampleTier | null>(null)

  return (
    <div className="space-y-px">
      {EXAMPLE_TIER_ORDER.map((tier) => {
        const examples = EXAMPLE_QUERIES.filter((example) => example.tier === tier)
        const isOpen = openTier === tier
        return (
          <div key={tier} className="border border-line">
            <button
              type="button"
              onClick={() => setOpenTier(isOpen ? null : tier)}
              aria-expanded={isOpen}
              className={cn(
                'flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left',
                isOpen ? 'bg-panel-muted' : 'hover:bg-panel-muted',
              )}
            >
              <span className="flex min-w-0 items-baseline gap-2">
                <span className="truncate text-[12px] font-medium text-ink">
                  {EXAMPLE_TIER_LABELS[tier]}
                </span>
                <span className="shrink-0 font-mono text-[10px] text-ink-3">{examples.length}</span>
              </span>
              <ChevronDownIcon
                size={13}
                className={cn('shrink-0 text-ink-3 transition-transform', isOpen && 'rotate-180')}
              />
            </button>

            {isOpen ? (
              <ul className="border-t border-line">
                {examples.map((example) => (
                  <li key={example.id} className="border-b border-line last:border-b-0">
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => fillDraft(example.text)}
                      title={example.note}
                      className="w-full px-2 py-1.5 text-left hover:bg-accent-soft/35 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                    >
                      <span
                        className={cn(
                          'block text-[12px] leading-snug',
                          disabled ? 'text-ink-3' : 'text-ink',
                        )}
                      >
                        {example.text}
                      </span>
                      <span className="mt-0.5 block text-[11px] leading-snug text-ink-3">
                        {example.note}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
