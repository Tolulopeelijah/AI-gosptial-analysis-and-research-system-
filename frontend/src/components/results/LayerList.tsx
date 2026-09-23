import { cn } from '@/lib/cn'
import { buildLegend } from '@/lib/legend'
import { formatCompact } from '@/lib/format'
import { PALETTE } from '@/lib/palette'
import { LineIcon, MapPinIcon, PolygonIcon } from '@/components/ui/Icons'
import type { GeographicResult } from '@/types/geospatial'

/**
 * Every layer currently on the map, including the context layers.
 *
 * The legend over the map explains the drawing; this explains the response —
 * which layers the backend returned, what each one is for, and how many
 * features it carries. Context layers are called out as such, so a buffer ring
 * is never mistaken for part of the answer.
 */
export function LayerList({ results }: { results: GeographicResult[] }) {
  const legend = buildLegend(results)
  const entriesById = new Map(legend.entries.map((entry) => [entry.id, entry]))

  return (
    <ul className="divide-y divide-line border border-line">
      {results.map((result) => {
        const entry = entriesById.get(result.id)
        const count = result.metadata?.count ?? 0
        const isContext = result.metadata?.role === 'context'
        const kind = entry?.kind ?? 'polygon'
        const Icon = kind === 'point' ? MapPinIcon : kind === 'line' ? LineIcon : PolygonIcon
        // A graduated layer is identified by its darkest class; a flat one by its
        // own colour.
        const ramp = entry?.swatches
        const swatch =
          (ramp && ramp.length > 0 ? ramp[ramp.length - 1]?.color : entry?.color) ?? PALETTE.other

        return (
          <li key={result.id} className="flex items-start gap-2 px-2 py-1.5">
            <span
              className={cn(
                'mt-[3px] size-2.5 shrink-0 border',
                kind === 'point' ? 'rounded-full' : 'rounded-[1px]',
                kind === 'line' && 'h-0.5 w-3.5 rounded-none border-0',
              )}
              style={{ backgroundColor: swatch, borderColor: swatch }}
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1.5">
                  <Icon size={12} className="shrink-0 text-ink-3" />
                  <span className="truncate text-[12px] text-ink">
                    {result.metadata?.title ?? 'Result layer'}
                  </span>
                  {isContext ? (
                    <span className="shrink-0 rounded-[2px] border border-line-strong bg-panel-muted px-1 text-[9px] uppercase tracking-[0.06em] text-ink-3">
                      context
                    </span>
                  ) : null}
                </span>
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-ink-3">
                  {count > 0 ? formatCompact(count) : '—'}
                </span>
              </div>
              {result.metadata?.description ? (
                <p className="mt-0.5 text-[11px] leading-snug text-ink-3">
                  {result.metadata.description}
                </p>
              ) : null}
              <div className="mt-0.5 flex flex-wrap gap-x-2 font-mono text-[10px] text-ink-3">
                {result.metadata?.geometryType ? <span>{result.metadata.geometryType}</span> : null}
                {result.choropleth ? (
                  <span>
                    graduated · {result.choropleth.legendTitle} ·{' '}
                    {result.choropleth.breaks.length + 1} classes
                  </span>
                ) : null}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
