import { buildLegend } from '@/lib/legend'
import { cn } from '@/lib/cn'
import { LineIcon, MapPinIcon, PolygonIcon } from '@/components/ui/Icons'
import type { GeographicResult } from '@/types/geospatial'
import type { LegendEntry } from '@/types/map'

/**
 * Map legend.
 *
 * Always present when there is something drawn: the moment a map carries a
 * graduated fill or more than one layer, colour alone is not a sufficient
 * explanation. A graduated layer lists its real class ranges — the numbers come
 * from the same break computation the map uses to shade the polygons.
 */
export function MapLegend({
  results,
  visible,
}: {
  results: GeographicResult[]
  visible: boolean
}) {
  const legend = buildLegend(results)
  if (legend.entries.length === 0) return null

  return (
    <div className="flex max-h-full flex-col overflow-hidden rounded-[3px] border border-line-strong bg-panel/95 shadow-[0_2px_10px_rgb(11_11_11/0.08)] backdrop-blur-[2px]">
      <div className="flex items-center justify-between border-b border-line px-2.5 py-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-2">
          Legend
        </span>
        {!visible ? (
          <span className="text-[10px] text-ink-3">layer hidden</span>
        ) : null}
      </div>
      <div className="min-h-0 overflow-y-auto px-2.5 py-2">
        <ul className="space-y-2.5">
          {legend.entries.map((entry) => (
            <li key={entry.id} className={cn(!visible && 'opacity-45')}>
              <LegendRow entry={entry} />
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function LegendRow({ entry }: { entry: LegendEntry }) {
  if (entry.swatches && entry.swatches.length > 0) {
    return (
      <div>
        <div className="flex items-center gap-1.5">
          <PolygonIcon size={13} className="shrink-0 text-ink-3" />
          <span className="truncate text-[11px] font-medium text-ink">{entry.label}</span>
        </div>
        {entry.rampTitle ? (
          <div className="mt-1 text-[10px] uppercase tracking-[0.06em] text-ink-3">
            {entry.rampTitle}
          </div>
        ) : null}
        <ul className="mt-1 space-y-[3px]">
          {[...entry.swatches].reverse().map((swatch) => (
            <li key={swatch.label} className="flex items-center gap-1.5">
              <span
                className="size-2.5 shrink-0 rounded-[1px] border border-black/12"
                style={{ backgroundColor: swatch.color }}
                aria-hidden="true"
              />
              <span className="font-mono text-[10px] tabular-nums text-ink-2">{swatch.label}</span>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  const Icon = entry.kind === 'point' ? MapPinIcon : entry.kind === 'line' ? LineIcon : PolygonIcon
  return (
    <div className="flex items-center gap-1.5">
      {entry.kind === 'line' ? (
        <span
          className="h-0.5 w-3.5 shrink-0"
          style={{ backgroundColor: entry.color }}
          aria-hidden="true"
        />
      ) : (
        <span
          className={cn(
            'shrink-0 border',
            entry.kind === 'point' ? 'size-2.5 rounded-full' : 'size-3 rounded-[1px]',
          )}
          style={{
            backgroundColor: entry.kind === 'point' ? entry.color : `${entry.color}88`,
            borderColor: entry.color,
          }}
          aria-hidden="true"
        />
      )}
      <Icon size={12} className="shrink-0 text-ink-3" />
      <span className="truncate text-[11px] text-ink" title={entry.note ?? entry.label}>
        {entry.label}
      </span>
    </div>
  )
}
