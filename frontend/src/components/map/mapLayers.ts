import L from 'leaflet'
import type { Feature, GeoJsonObject } from 'geojson'
import { geometryLabelAnchor, toFeatures } from '@/lib/geo'
import { formatAttributeValue } from '@/lib/format'
import { PALETTE, seriesColor, seriesStroke } from '@/lib/palette'
import { choroplethColorFor, resultSymbol } from '@/lib/resultStyle'
import type { AttributeField, GeographicResult } from '@/types/geospatial'

interface BuildOptions {
  /** Multiplier from the map preferences (1 = the style's own opacity). */
  opacityMultiplier: number
  /** Tooltips are only bound for the layers that answer the query. */
  withTooltips: boolean
}

/**
 * Builds the Leaflet layer for one result.
 *
 * Everything the backend can return goes through here: a Point becomes a
 * circle marker, LineString/ MultiLineString a stroked path, Polygon and
 * MultiPolygon a filled path — and a FeatureCollection becomes all of its
 * features at once. Nothing is query-specific.
 */
export function buildResultLayer(result: GeographicResult, options: BuildOptions): L.Layer {
  const symbol = resultSymbol(result)
  const opacity = options.opacityMultiplier

  const styleFor = (feature?: Feature): L.PathOptions => {
    const style = result.style ?? {}
    const fillColor =
      result.choropleth && feature
        ? choroplethColorFor(result, feature)
        : style.fillColor ?? seriesColor(style.seriesSlot)
    const stroke = result.choropleth
      ? PALETTE.series1Stroke
      : (style.color ?? seriesStroke(style.seriesSlot))

    if (symbol === 'point') {
      return {
        color: style.color ?? PALETTE.pointerStroke,
        weight: style.weight ?? 1.5,
        opacity: (style.opacity ?? 1) * Math.min(1, opacity + 0.15),
        fillColor: style.fillColor ?? PALETTE.pointer,
        fillOpacity: (style.fillOpacity ?? 0.85) * opacity,
      }
    }

    if (symbol === 'line') {
      return {
        color: style.color ?? fillColor,
        weight: style.weight ?? 2,
        opacity: style.opacity ?? 0.95,
        dashArray: style.dashArray,
        fill: false,
      }
    }

    return {
      color: stroke,
      weight: result.choropleth ? 0.7 : (style.weight ?? 1),
      opacity: (style.opacity ?? 1) * Math.min(1, opacity + 0.2),
      fillColor,
      fillOpacity: (style.fillOpacity ?? 0.5) * opacity,
      dashArray: style.dashArray,
    }
  }

  const geoLayer = L.geoJSON(result.data as GeoJsonObject, {
    style: styleFor,
    pointToLayer: (feature, latlng) =>
      L.circleMarker(latlng, {
        ...styleFor(feature as Feature),
        radius: result.style?.radius ?? 6,
        renderer: undefined,
      }),
    onEachFeature: (feature, layer) => {
      if (!options.withTooltips) return
      const html = featureTooltipHtml(feature as Feature, result.metadata?.attributes)
      if (html) layer.bindTooltip(html, { direction: 'top', sticky: true, opacity: 1 })
    },
  })

  geoLayer.eachLayer((layer) => {
    const path = layer as L.Path
    if (typeof path.setStyle !== 'function') return
    // Hover emphasis: thicken the stroke and lift the fill without changing hue,
    // so identity (which is colour) stays stable while hovering.
    layer.on('mouseover', () => {
      const base = styleFor(undefined)
      path.setStyle({
        weight: (base.weight ?? 1) + 1.2,
        fillOpacity: Math.min(0.95, (base.fillOpacity ?? 0.5) + 0.18),
      })
      if (typeof path.bringToFront === 'function') path.bringToFront()
    })
    layer.on('mouseout', () => {
      geoLayer.resetStyle(layer as L.Path)
    })
  })

  return geoLayer
}

/** Applies a new opacity to an already-built result layer, without rebuilding it. */
export function restyleResultLayer(
  layer: L.Layer,
  result: GeographicResult,
  opacityMultiplier: number,
): void {
  if (!(layer instanceof L.GeoJSON)) return
  layer.setStyle((feature) => {
    const style = result.style ?? {}
    const symbol = resultSymbol(result)
    const fillColor =
      result.choropleth && feature
        ? choroplethColorFor(result, feature as Feature)
        : style.fillColor ?? seriesColor(style.seriesSlot)
    const stroke = result.choropleth
      ? PALETTE.series1Stroke
      : (style.color ?? seriesStroke(style.seriesSlot))
    if (symbol === 'line') {
      return {
        color: style.color ?? fillColor,
        weight: style.weight ?? 2,
        opacity: style.opacity ?? 0.95,
        fill: false,
      }
    }
    if (symbol === 'point') {
      return {
        color: style.color ?? PALETTE.pointerStroke,
        weight: style.weight ?? 1.5,
        fillColor: style.fillColor ?? PALETTE.pointer,
        fillOpacity: (style.fillOpacity ?? 0.85) * opacityMultiplier,
      }
    }
    return {
      color: stroke,
      weight: result.choropleth ? 0.7 : (style.weight ?? 1),
      fillColor,
      fillOpacity: (style.fillOpacity ?? 0.5) * opacityMultiplier,
    }
  })
}

const ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ESCAPES[char] ?? char)
}

/**
 * Tooltip body for a feature.
 *
 * Uses the result's declared attribute fields when the backend supplied them,
 * and otherwise shows the first few scalar properties, so an unknown payload
 * still produces something readable rather than an empty bubble.
 */
export function featureTooltipHtml(feature: Feature, attributes?: AttributeField[]): string {
  const properties = (feature.properties ?? {}) as Record<string, unknown>
  const fields: AttributeField[] =
    attributes && attributes.length > 0
      ? attributes.filter((field) => field.role !== 'id')
      : Object.entries(properties)
          .filter(([, value]) => value == null || ['string', 'number', 'boolean'].includes(typeof value))
          .slice(0, 5)
          .map(([key, value]) => ({
            key,
            label: key.replace(/_/g, ' '),
            type: typeof value === 'number' ? 'number' : 'string',
          }))

  const labelField = fields.find((field) => field.role === 'label') ?? fields[0]
  const title = labelField ? formatAttributeValue(properties[labelField.key], labelField.precision) : 'Feature'
  const rows = fields
    .filter((field) => field !== labelField)
    .slice(0, 4)
    .map(
      (field) =>
        `<div class="flex items-baseline justify-between gap-3"><span class="text-ink-3">${escapeHtml(
          field.label,
        )}</span><span class="font-mono tabular-nums text-ink">${escapeHtml(
          formatAttributeValue(properties[field.key], field.precision),
        )}${field.unit ? `<span class="text-ink-3"> ${escapeHtml(field.unit)}</span>` : ''}</span></div>`,
    )
    .join('')

  return `<div class="min-w-[9rem]"><div class="text-[12px] font-semibold text-ink">${escapeHtml(
    String(title),
  )}</div>${rows ? `<div class="mt-1 space-y-0.5 text-[11px]">${rows}</div>` : ''}</div>`
}

/**
 * Small dot markers for the reference places layer.
 *
 * These are basemap context, not query results — hence the neutral treatment
 * rather than a data-series colour.
 */
export function buildPlacesLayer(
  places: Array<{ id: string; name: string; state: string; center: { lat: number; lng: number } }>,
): L.LayerGroup {
  const group = L.layerGroup()
  for (const place of places) {
    const marker = L.circleMarker([place.center.lat, place.center.lng], {
      radius: 3.5,
      color: PALETTE.ink2,
      weight: 1.2,
      opacity: 0.85,
      fillColor: PALETTE.panel,
      fillOpacity: 0.9,
    })
    marker.bindTooltip(`${escapeHtml(place.name)}, ${escapeHtml(place.state)}`, {
      direction: 'right',
      offset: [6, 0],
      opacity: 1,
    })
    group.addLayer(marker)
  }
  return group
}

/** County name labels for a result layer, placed at each polygon's anchor. */
export function buildLabelLayer(result: GeographicResult, maxLabels = 300): L.LayerGroup {
  const group = L.layerGroup()
  const features = toFeatures(result.data).slice(0, maxLabels)
  for (const feature of features) {
    const anchor = geometryLabelAnchor(feature.geometry)
    if (!anchor) continue
    const properties = (feature.properties ?? {}) as Record<string, unknown>
    const name =
      (typeof properties.name === 'string' && properties.name) ||
      (typeof properties.NAME === 'string' && properties.NAME) ||
      ''
    if (!name) continue
    const marker = L.marker([anchor.lat, anchor.lng], {
      interactive: false,
      keyboard: false,
      icon: L.divIcon({
        className: 'weis-label',
        html: escapeHtml(name),
        iconSize: undefined,
      }),
    })
    group.addLayer(marker)
  }
  return group
}
