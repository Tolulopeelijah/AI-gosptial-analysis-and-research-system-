import type { Feature } from 'geojson'
import type { AttributeField, ChoroplethSpec, GeographicResult, SymbolKind } from '@/types/geospatial'
import { classIndexFor, geometryKind, numericProperty, toFeatures } from '@/lib/geo'
import { PALETTE, sequentialSteps, seriesColor, seriesStroke } from '@/lib/palette'

/**
 * How a result should look.
 *
 * Shared by the layer builder (which draws it) and the legend (which explains
 * it) so the two can never disagree about what colour a layer is.
 */

export function resultSymbol(result: GeographicResult): SymbolKind {
  if (result.style?.symbol) return result.style.symbol
  const features = toFeatures(result.data)
  return features.length > 0 ? geometryKind(features[0].geometry) : 'polygon'
}

export function choroplethClassCount(result: GeographicResult): number {
  return result.choropleth ? result.choropleth.breaks.length + 1 : 0
}

/** The ramp steps a graduated result is using, lightest (lowest) first. */
export function choroplethSteps(result: GeographicResult): string[] {
  if (!result.choropleth) return []
  return sequentialSteps(choroplethClassCount(result), result.choropleth.hue ?? 'blue')
}

export function choroplethColorFor(result: GeographicResult, feature: Feature): string {
  const spec = result.choropleth
  if (!spec) return result.style?.fillColor ?? seriesColor(result.style?.seriesSlot)
  const value = numericProperty(feature, spec.attribute)
  if (value == null) return PALETTE.line
  const steps = choroplethSteps(result)
  const index = classIndexFor(value, spec.breaks)
  return steps[Math.min(index, steps.length - 1)] ?? seriesColor(result.style?.seriesSlot)
}

/** A single representative colour, for legend swatches of non-graduated layers. */
export function resultColor(result: GeographicResult): string {
  if (result.choropleth) {
    const steps = choroplethSteps(result)
    return steps[Math.floor(steps.length / 2)] ?? PALETTE.series1
  }
  if (result.style?.fillColor) return result.style.fillColor
  if (resultSymbol(result) === 'point') return PALETTE.pointer
  return seriesColor(result.style?.seriesSlot)
}

export function resultStroke(result: GeographicResult): string {
  if (result.choropleth) return PALETTE.series1Stroke
  if (result.style?.color) return result.style.color
  if (resultSymbol(result) === 'point') return PALETTE.pointerStroke
  return seriesStroke(result.style?.seriesSlot)
}

/**
 * Class ranges for a graduated result, as legend rows.
 * e.g. "1,024 – 18,300", "18,300 – 44,900", …, "412,000 – 4,700,000"
 */
export function choroplethLegendRows(
  spec: ChoroplethSpec,
  steps: string[],
  format: (value: number) => string,
): Array<{ color: string; label: string }> {
  const boundaries = [spec.min, ...spec.breaks, spec.max]
  return steps.map((color, index) => {
    // `steps` is one shorter than `boundaries`, so both reads are in range; the
    // fallbacks only guard a backend that sends mismatched breaks.
    const lower = boundaries[index] ?? spec.min
    const upper = boundaries[index + 1] ?? spec.max
    const isLast = index === steps.length - 1
    return {
      color,
      label: `${format(lower)} – ${format(upper)}${isLast ? '+' : ''}`,
    }
  })
}

/** Fields to show in a table or tooltip: declared fields, else inferred. */
export function resolveAttributeFields(result: GeographicResult): AttributeField[] {
  const declared = result.metadata?.attributes
  if (declared && declared.length > 0) return declared
  const [first] = toFeatures(result.data)
  if (!first?.properties) return []
  return Object.entries(first.properties)
    .filter(([, value]) => value == null || ['string', 'number', 'boolean'].includes(typeof value))
    .slice(0, 8)
    .map(([key, value]) => ({
      key,
      label: key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase()),
      type: typeof value === 'number' ? ('number' as const) : ('string' as const),
    }))
}

/** Numeric values of an attribute across a result, for distributions. */
export function attributeValues(result: GeographicResult, key: string): number[] {
  return toFeatures(result.data)
    .map((feature) => numericProperty(feature, key))
    .filter((value): value is number => value != null)
}
