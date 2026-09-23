import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/**
 * A single figure with a label.
 *
 * No sparkline, no chart: when the data's job is one number, the number is the
 * visualisation. Values use tabular figures so a row of tiles lines up, and the
 * text wears ink tokens rather than any series colour.
 */
export function StatTile({
  label,
  value,
  note,
  title,
  className,
}: {
  label: string
  value: ReactNode
  /** Secondary line under the value — units, provenance. */
  note?: string
  title?: string
  className?: string
}) {
  return (
    <div
      title={title}
      className={cn(
        'min-w-0 border border-line bg-panel px-2.5 py-1.5',
        className,
      )}
    >
      <div className="text-[10px] font-medium uppercase tracking-[0.06em] text-ink-3">{label}</div>
      <div className="mt-0.5 truncate font-mono text-[15px] leading-tight tabular-nums text-ink">
        {value}
      </div>
      {note ? <div className="mt-0.5 truncate text-[10px] text-ink-3">{note}</div> : null}
    </div>
  )
}
