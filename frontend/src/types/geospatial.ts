import type { Feature, FeatureCollection, GeoJsonObject } from 'geojson'

/**
 * Data-series slots.
 *
 * Identity (which result layer is which) is encoded with a fixed-order palette
 * of three slots. Slots are assigned in order and never cycled: a fourth result
 * layer does not get a generated hue, it gets the neutral "other" treatment.
 * See README → "Colour system".
 */
export type SeriesSlot = 1 | 2 | 3

export type SymbolKind = 'polygon' | 'line' | 'point'

export interface ResultStyle {
  /** Polygon / marker fill. */
  fillColor?: string
  /** Stroke colour (and marker stroke). */
  color?: string
  fillOpacity?: number
  opacity?: number
  weight?: number
  radius?: number
  dashArray?: string
  /** Overrides the symbol inferred from the geometry, for the legend. */
  symbol?: SymbolKind
  seriesSlot?: SeriesSlot
}

export type AttributeValue = string | number | boolean | null

export interface AttributeField {
  key: string
  label: string
  type: 'string' | 'number'
  /** `label` renders as the feature title; `value` drives tables and encoding. */
  role?: 'id' | 'label' | 'value'
  /** Appended in tables and tooltips, e.g. "people" or "km". */
  unit?: string
  /** Significant digits for display, for float attributes. */
  precision?: number
}

/**
 * Graduated colour encoding for a result layer.
 *
 * This is the "magnitude" job in the colour system: a single-hue sequential
 * ramp, light -> dark, with explicit class breaks so the legend can print real
 * ranges rather than a vague gradient.
 */
export interface ChoroplethSpec {
  attribute: string
  label: string
  unit?: string
  /** Human-readable legend title, e.g. "Population (2020)". */
  legendTitle: string
  /** Ascending class boundaries; n boundaries produce n + 1 classes. */
  breaks: number[]
  min: number
  max: number
  hue?: 'blue' | 'orange'
}

export interface GeographicResultMetadata {
  /** Short noun phrase for the legend, e.g. "Counties". */
  title?: string
  description?: string
  /** Number of features in `data`. */
  count?: number
  /** Dataset the features came from, e.g. "US Counties (2020 census)". */
  dataset?: string
  /** Human label for the geometry, e.g. "MultiPolygon". */
  geometryType?: string
  /**
   * What the layer is for. `primary` layers answer the query and are what the
   * results panel counts; `context` layers are supporting geometry the query
   * implies (a buffer ring, a reference marker, the query region itself).
   */
  role?: 'primary' | 'context'
  /**
   * Fields the backend declares for this result. When present the UI can build
   * tables and tooltips without guessing at the property shape.
   */
  attributes?: AttributeField[]
}

/**
 * The unit of everything the backend returns that is drawable.
 *
 * The frontend never assumes a particular query produced a particular shape:
 * anything that satisfies this interface can be rendered, listed, and fitted.
 */
export interface GeographicResult {
  id: string
  type: 'FeatureCollection' | 'Feature'
  data: FeatureCollection | Feature | GeoJsonObject
  style?: ResultStyle
  metadata?: GeographicResultMetadata
  choropleth?: ChoroplethSpec
}

/**
 * A knowledge source behind an answer.
 *
 * `ref` (S1, S2, …) matches the inline [S#] markers in the explanation, so
 * every cited claim resolves to exactly one entry here. Markers without a
 * matching entry are stripped by the backend and never render.
 */
export interface KnowledgeReference {
  ref: string
  title?: string
  identifier?: string
  url?: string
  source?: string
}

export interface BoundingBox {
  west: number
  south: number
  east: number
  north: number
}

export interface LatLng {
  lat: number
  lng: number
}

/**
 * Extra context the UI may attach to a query.
 *
 * Nothing populates this yet — it is the seam for future map input (a drawn
 * polygon, a selected county, a clicked point). Keeping it in the request
 * contract now means those features are additive later.
 */
export interface QueryContext {
  mapBounds?: BoundingBox
  mapCenter?: LatLng
  mapZoom?: number
  /** GeoJSON produced by a future draw/select tool. */
  selection?: GeoJsonObject
  /** Free-form labels for whatever produced `selection`, e.g. "drawn polygon". */
  selectionLabel?: string
}
