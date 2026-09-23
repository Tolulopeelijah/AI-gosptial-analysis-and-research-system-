import { formatCompact } from '@/lib/format'
import { choroplethLegendRows, choroplethSteps, resultColor, resultStroke, resultSymbol } from '@/lib/resultStyle'
import type { GeographicResult } from '@/types/geospatial'
import type { LegendEntry, LegendModel } from '@/types/map'

/**
 * Builds the legend for whatever is currently on the map.
 *
 * Rules it follows (from the project's colour system):
 *   - one legend row per result layer, in draw order, primary layers first
 *   - a graduated result shows its actual class ranges, not a vague gradient
 *   - a single-series map still gets a legend, because the encoding here is a
 *     choropleth or a multi-layer overlay — never a bare one-colour chart
 */
export function buildLegend(results: GeographicResult[]): LegendModel {
  const ordered = [...results].sort((a, b) => {
    const aContext = a.metadata?.role === 'context' ? 1 : 0
    const bContext = b.metadata?.role === 'context' ? 1 : 0
    return aContext - bContext
  })

  const entries: LegendEntry[] = []

  for (const result of ordered) {
    const count = result.metadata?.count ?? 0
    const title = result.metadata?.title ?? 'Result'
    const isContext = result.metadata?.role === 'context'

    if (result.choropleth) {
      const steps = choroplethSteps(result)
      entries.push({
        id: result.id,
        label: `${title} (${formatCompact(count)})`,
        kind: 'polygon',
        swatches: choroplethLegendRows(result.choropleth, steps, formatCompact),
        rampTitle: result.choropleth.legendTitle,
        note: result.metadata?.description,
      })
      continue
    }

    entries.push({
      id: result.id,
      label: `${title}${count > 0 ? ` (${formatCompact(count)})` : ''}`,
      kind: resultSymbol(result),
      color: resultSymbol(result) === 'line' ? resultStroke(result) : resultColor(result),
      seriesSlot: result.style?.seriesSlot,
      note: isContext ? result.metadata?.description : undefined,
    })
  }

  return { entries }
}
