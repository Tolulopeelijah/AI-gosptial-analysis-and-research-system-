import type { BoundingBox, LatLng } from '@/types/geospatial'

/**
 * The imperative handle a map implementation exposes to the rest of the app.
 *
 * Panels never touch Leaflet. They call these methods, so the map library stays
 * an implementation detail of `components/map/`.
 */
export interface MapController {
  zoomIn(): void
  zoomOut(): void
  /** Return to the extent the dataset covers. */
  resetView(): void
  /** Fit the current result layers. No-op when there are none. */
  fitResults(): void
  toggleFullscreen(): void
  getBounds(): BoundingBox | null
  getCenter(): LatLng | null
  getZoom(): number | null
  hasResults(): boolean
}

export const NOOP_MAP_CONTROLLER: MapController = {
  zoomIn: () => {},
  zoomOut: () => {},
  resetView: () => {},
  fitResults: () => {},
  toggleFullscreen: () => {},
  getBounds: () => null,
  getCenter: () => null,
  getZoom: () => null,
  hasResults: () => false,
}
