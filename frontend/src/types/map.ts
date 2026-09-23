import type { LatLng, SeriesSlot, SymbolKind } from './geospatial'

export type BasemapId = 'positron' | 'positron-labels' | 'osm' | 'topo'

export interface BasemapDefinition {
  id: BasemapId
  name: string
  url: string
  attribution: string
  maxZoom: number
  /** True when the tiles carry their own place labels. */
  hasLabels: boolean
}

/** User-controlled visibility of the non-basemap layers. */
export interface LayerVisibility {
  /** Everything the backend returned for the current run. */
  results: boolean
  /** County name labels drawn over the result polygons. */
  labels: boolean
  /** Reference markers for the cities the query mentions. */
  places: boolean
}

export interface MapViewState {
  center: LatLng
  zoom: number
}

export interface MapPreferences {
  basemap: BasemapId
  visibility: LayerVisibility
  /** Fill opacity multiplier applied to result layers (0.15 - 1). */
  resultOpacity: number
}

export type LegendSwatchKind = SymbolKind

/** One row of the legend. */
export interface LegendEntry {
  id: string
  label: string
  kind: LegendSwatchKind
  /** Single colour, used when `swatches` is absent. */
  color?: string
  seriesSlot?: SeriesSlot
  /** True for the ramp swatches of a graduated encoding. */
  swatches?: Array<{ color: string; label: string }>
  /** Ramp caption, e.g. "Population (2020)". */
  rampTitle?: string
  note?: string
}

export interface LegendModel {
  entries: LegendEntry[]
}
