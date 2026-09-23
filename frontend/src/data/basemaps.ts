import type { BasemapDefinition, BasemapId } from '@/types/map'

/**
 * Basemap tiles.
 *
 * All four are light, low-saturation styles on purpose: the result layers are
 * the only saturated thing on screen, and the validated colour palette is
 * specified against a light surface. A dark basemap would need its own ramp
 * steps, so it is deliberately not offered.
 *
 * Attribution is required by every provider listed here and is rendered by the
 * map's attribution control.
 */
export const BASEMAPS: Record<BasemapId, BasemapDefinition> = {
  positron: {
    id: 'positron',
    name: 'Positron (no labels)',
    url: 'https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png',
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    maxZoom: 20,
    hasLabels: false,
  },
  'positron-labels': {
    id: 'positron-labels',
    name: 'Positron (labels)',
    url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    maxZoom: 20,
    hasLabels: true,
  },
  osm: {
    id: 'osm',
    name: 'OpenStreetMap',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
    hasLabels: true,
  },
  topo: {
    id: 'topo',
    name: 'OpenTopoMap',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution:
      'Map data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM | Map style &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)',
    maxZoom: 17,
    hasLabels: true,
  },
}

export const BASEMAP_ORDER: BasemapId[] = ['osm', 'positron', 'positron-labels', 'topo']

/**
 * Default basemap.
 *
 * Plain OpenStreetMap: it needs no API key. (CARTO's Positron tiles now
 * render an "API key required" watermark for keyless use, so they stay
 * selectable but are not the default.)
 */
export const DEFAULT_BASEMAP: BasemapId = 'osm'

/** Where the map sits before any result arrives: Lucas County, Ohio. */
export const INITIAL_VIEW = {
  center: { lat: 41.65, lng: -83.55 },
  zoom: 10,
}
