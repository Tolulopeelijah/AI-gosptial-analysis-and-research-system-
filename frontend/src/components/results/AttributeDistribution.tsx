import { useMemo, useState } from 'react'
import { cn } from '@/lib/cn'
import { attributeValues, resolveAttributeFields } from '@/lib/resultStyle'
import { formatCompact, formatNumber } from '@/lib/format'
import { PALETTE } from '@/lib/palette'
import type { GeographicResult } from '@/types/geospatial'

const BIN_COUNT = 14

/**
 * Distribution of one numeric attribute across a result set.
 *
 * A single series, so there is no legend — the heading names the measure. The
 * bars show count per class, which is what makes a threshold query legible:
 * "population above 100,000" is easier to trust when you can see how much of
 * the distribution sits above the cut.
 *
 * Hovering a class reports its range and count in the readout below the plot
 * (and in the native title), so the figure is legible without colour.
 */
export function AttributeDistribution({ result }: { result: GeographicResult }) {
  const fields = useMemo(() => resolveAttributeFields(result), [result])
  const numericFields = useMemo(
    () => fields.filter((field) => field.type === 'number' && field.role !== 'id'),
    [fields],
  )

  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const activeField =
    numericFields.find((field) => field.key === selectedKey) ?? numericFields[0] ?? null

  const histogram = useMemo(() => {
    if (!activeField) return null
    const values = attributeValues(result, activeField.key)
    if (values.length < 2) return null
    return buildHistogram(values, BIN_COUNT)
  }, [result, activeField])

  if (numericFields.length === 0) return null

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
          Distribution
        </span>
        {numericFields.length > 1 ? (
          <select
            value={activeField?.key ?? ''}
            onChange={(event) => setSelectedKey(event.target.value)}
            className="max-w-[50%] rounded-[2px] border border-line-strong bg-panel px-1 py-0.5 text-[11px] text-ink-2"
            aria-label="Distribution attribute"
          >
            {numericFields.map((field) => (
              <option key={field.key} value={field.key}>
                {field.label}
              </option>
            ))}
          </select>
        ) : (
          <span className="truncate text-[11px] text-ink-2">{activeField?.label}</span>
        )}
      </div>

      {histogram ? (
        <Histogram
          bins={histogram.bins}
          max={histogram.max}
          unit={activeField?.unit}
          label={activeField?.label ?? ''}
        />
      ) : (
        <p className="text-[11px] text-ink-3">
          Not enough distinct values of {activeField?.label ?? 'this attribute'} to plot.
        </p>
      )}
    </div>
  )
}

interface Bin {
  start: number
  end: number
  count: number
}

function buildHistogram(values: number[], binCount: number): { bins: Bin[]; max: number } {
  let min = Infinity
  let max = -Infinity
  for (const value of values) {
    if (value < min) min = value
    if (value > max) max = value
  }
  const span = max - min || 1
  const width = span / binCount
  const bins: Bin[] = Array.from({ length: binCount }, (_, index) => ({
    start: min + index * width,
    end: min + (index + 1) * width,
    count: 0,
  }))

  for (const value of values) {
    const index = Math.min(binCount - 1, Math.floor((value - min) / width))
    bins[index].count += 1
  }

  return { bins, max: Math.max(...bins.map((bin) => bin.count), 1) }
}

function Histogram({
  bins,
  max,
  label,
  unit,
}: {
  bins: Bin[]
  max: number
  label: string
  unit?: string
}) {
  const [hovered, setHovered] = useState<number | null>(null)
  const active = hovered != null ? bins[hovered] : null

  return (
    <div className="relative">
      {/* One bar per class; 2px surface gap between fills, square data-ends. */}
      <div className="flex h-16 items-end gap-[2px]" role="img" aria-label={`${label} distribution`}>
        {bins.map((bin, index) => (
          <button
            key={`${bin.start}-${index}`}
            type="button"
            onMouseEnter={() => setHovered(index)}
            onMouseLeave={() => setHovered(null)}
            onFocus={() => setHovered(index)}
            onBlur={() => setHovered(null)}
            title={`${formatCompact(bin.start)} – ${formatCompact(bin.end)}: ${bin.count}`}
            className="group relative min-w-0 flex-1 cursor-default"
            style={{ height: `${Math.max(2, (bin.count / max) * 100)}%` }}
          >
            <span
              className={cn(
                'block h-full w-full transition-opacity',
                hovered != null && hovered !== index ? 'opacity-55' : 'opacity-100',
              )}
              style={{ backgroundColor: PALETTE.series1 }}
            />
          </button>
        ))}
      </div>

      {/* Recessive axis: endpoints only, in muted ink. */}
      <div className="mt-1 flex justify-between border-t border-line pt-1 font-mono text-[10px] tabular-nums text-ink-3">
        <span>{formatCompact(bins[0]?.start ?? 0)}</span>
        {unit ? <span className="text-ink-3">{unit}</span> : null}
        <span>{formatCompact(bins[bins.length - 1]?.end ?? 0)}</span>
      </div>

      <div className="mt-1 min-h-[14px] text-[11px] text-ink-2">
        {active ? (
          <span>
            <span className="font-mono tabular-nums">
              {formatNumber(active.start)} – {formatNumber(active.end)}
            </span>
            {' · '}
            <span className="text-ink">
              {formatCompact(active.count)} {active.count === 1 ? 'feature' : 'features'}
            </span>
          </span>
        ) : (
          <span className="text-ink-3">Hover a class to read its range and count</span>
        )}
      </div>
    </div>
  )
}
