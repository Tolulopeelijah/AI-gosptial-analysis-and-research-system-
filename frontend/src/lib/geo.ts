import type {
  Feature,
  FeatureCollection,
  GeoJsonObject,
  Geometry,
  GeometryCollection,
  Position,
} from 'geojson'
import type { BoundingBox, LatLng, SymbolKind } from '@/types/geospatial'

const EARTH_RADIUS_KM = 6371.0088

export function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180
}

/** Great-circle distance in kilometres. */
export function haversineKm(a: LatLng, b: LatLng): number {
  const dLat = toRadians(b.lat - a.lat)
  const dLng = toRadians(b.lng - a.lng)
  const lat1 = toRadians(a.lat)
  const lat2 = toRadians(b.lat)
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)))
}

export function positionToLatLng(position: Position): LatLng {
  return { lng: position[0], lat: position[1] }
}

/** Every position in a geometry, in document order. */
export function* geometryPositions(geometry: Geometry | null | undefined): Generator<Position> {
  if (!geometry) return
  switch (geometry.type) {
    case 'Point':
      yield geometry.coordinates
      return
    case 'MultiPoint':
    case 'LineString':
      for (const position of geometry.coordinates) yield position
      return
    case 'MultiLineString':
    case 'Polygon':
      for (const part of geometry.coordinates) for (const position of part) yield position
      return
    case 'MultiPolygon':
      for (const polygon of geometry.coordinates)
        for (const ring of polygon) for (const position of ring) yield position
      return
    case 'GeometryCollection':
      for (const child of geometry.geometries) yield* geometryPositions(child)
      return
    default:
      return
  }
}

/** Rings of a geometry (outer rings only for the bbox/centroid helpers below). */
function* geometryRings(geometry: Geometry | null | undefined): Generator<Position[]> {
  if (!geometry) return
  switch (geometry.type) {
    case 'Polygon':
      yield* geometry.coordinates
      return
    case 'MultiPolygon':
      for (const polygon of geometry.coordinates) yield* polygon
      return
    case 'GeometryCollection':
      for (const child of geometry.geometries) yield* geometryRings(child)
      return
    default:
      return
  }
}

export function emptyBounds(): BoundingBox {
  return { west: Infinity, south: Infinity, east: -Infinity, north: -Infinity }
}

export function isEmptyBounds(bounds: BoundingBox): boolean {
  return !Number.isFinite(bounds.west) || bounds.west > bounds.east
}

export function extendBounds(bounds: BoundingBox, position: Position): BoundingBox {
  const [lng, lat] = position
  return {
    west: Math.min(bounds.west, lng),
    south: Math.min(bounds.south, lat),
    east: Math.max(bounds.east, lng),
    north: Math.max(bounds.north, lat),
  }
}

export function geometryBounds(geometry: Geometry | null | undefined): BoundingBox | null {
  let bounds = emptyBounds()
  let seen = false
  for (const position of geometryPositions(geometry)) {
    bounds = extendBounds(bounds, position)
    seen = true
  }
  return seen ? bounds : null
}

export function featureBounds(feature: Feature): BoundingBox | null {
  return geometryBounds(feature.geometry)
}

export function unionBounds(all: Array<BoundingBox | null>): BoundingBox | null {
  let bounds = emptyBounds()
  let seen = false
  for (const candidate of all) {
    if (!candidate) continue
    bounds = {
      west: Math.min(bounds.west, candidate.west),
      south: Math.min(bounds.south, candidate.south),
      east: Math.max(bounds.east, candidate.east),
      north: Math.max(bounds.north, candidate.north),
    }
    seen = true
  }
  return seen ? bounds : null
}

export function boundsCenter(bounds: BoundingBox): LatLng {
  return { lat: (bounds.south + bounds.north) / 2, lng: (bounds.west + bounds.east) / 2 }
}

/** True for a dateline-crossing or polar bounds, which Leaflet cannot fit. */
export function isBoundsRenderable(bounds: BoundingBox): boolean {
  if (isEmptyBounds(bounds)) return false
  const latSpan = bounds.north - bounds.south
  const lngSpan = bounds.east - bounds.west
  return latSpan <= 180 && lngSpan <= 360
}

/**
 * Label anchor for a geometry.
 *
 * Uses the bounding-box centre of the largest ring. That is a deliberate
 * approximation: a true pole-of-inaccessibility is overkill for county labels
 * and this never lands outside a convex-ish shape's neighbourhood.
 */
export function geometryLabelAnchor(geometry: Geometry | null | undefined): LatLng | null {
  let best: { area: number; center: LatLng } | null = null
  for (const ring of geometryRings(geometry)) {
    const bounds = ring.reduce<BoundingBox>((acc, position) => extendBounds(acc, position), emptyBounds())
    if (isEmptyBounds(bounds)) continue
    const area = (bounds.east - bounds.west) * (bounds.north - bounds.south)
    if (!best || area > best.area) best = { area, center: boundsCenter(bounds) }
  }
  if (best) return best.center
  // Points / lines: fall back to the vertex average.
  let lat = 0
  let lng = 0
  let count = 0
  for (const position of geometryPositions(geometry)) {
    lng += position[0]
    lat += position[1]
    count++
  }
  return count ? { lat: lat / count, lng: lng / count } : null
}

/** Ray-casting test against a single ring (even-odd, so holes work when XOR'd). */
export function isPositionInRing(point: LatLng, ring: Position[]): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    const intersects =
      yi > point.lat !== yj > point.lat &&
      point.lng < ((xj - xi) * (point.lat - yi)) / (yj - yi || Number.EPSILON) + xi
    if (intersects) inside = !inside
  }
  return inside
}

export function isPositionInGeometry(point: LatLng, geometry: Geometry | null | undefined): boolean {
  if (!geometry) return false
  if (geometry.type === 'Polygon') {
    let inside = false
    for (const ring of geometry.coordinates) if (isPositionInRing(point, ring)) inside = !inside
    return inside
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.some((polygon) => {
      let inside = false
      for (const ring of polygon) if (isPositionInRing(point, ring)) inside = !inside
      return inside
    })
  }
  return false
}

/**
 * Distance from a point to a geometry, in kilometres, measured to the nearest
 * vertex of the (already simplified) geometry.
 *
 * This is the correct-by-construction version: great-circle distance over every
 * vertex.
 */
export function distanceToGeometryKm(point: LatLng, geometry: Geometry | null | undefined): number {
  let best = Infinity
  for (const position of geometryPositions(geometry)) {
    const distance = haversineKm(point, positionToLatLng(position))
    if (distance < best) best = distance
  }
  return best
}

/** Normalises anything drawable into a flat feature list. */
export function toFeatures(data: GeoJsonObject | null | undefined): Feature[] {
  if (!data) return []
  if (data.type === 'FeatureCollection') return (data as FeatureCollection).features
  if (data.type === 'Feature') return [data as Feature]
  if (data.type === 'GeometryCollection') {
    // `GeoJsonObject` is a single interface rather than a discriminated union, so
    // the `type` check narrows the property but not the object — hence the cast,
    // as in the two branches above.
    const collection = data as GeometryCollection
    return collection.geometries.map((geometry, index) => ({
      type: 'Feature',
      id: index,
      properties: {},
      geometry,
    }))
  }
  return [{ type: 'Feature', id: 0, properties: {}, geometry: data as Geometry }]
}

export function geometryKind(geometry: Geometry | null | undefined): SymbolKind {
  const type = geometry?.type
  if (type === 'Point' || type === 'MultiPoint') return 'point'
  if (type === 'LineString' || type === 'MultiLineString') return 'line'
  return 'polygon'
}

/** Label for the results panel, e.g. "MultiPolygon" or "FeatureCollection". */
export function describeGeometry(features: Feature[]): string {
  if (features.length === 0) return 'No geometry'
  if (features.length === 1) return features[0].geometry?.type ?? 'Feature'
  const kinds = new Set(features.map((feature) => feature.geometry?.type ?? 'Unknown'))
  if (kinds.size === 1) return `${[...kinds][0]} × ${features.length}`
  return `Mixed geometry × ${features.length}`
}

export function numericProperty(feature: Feature, key: string): number | null {
  const raw = (feature.properties ?? {})[key]
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string') {
    const parsed = Number(raw)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

/**
 * Quantile class breaks.
 *
 * Graduated colour for a magnitude attribute: equal-count classes so each
 * legend swatch holds comparable weight, which reads better than equal-interval
 * on skewed data like county population.
 */
export function quantileBreaks(values: number[], classes: number): number[] {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  if (sorted.length === 0) return []
  if (sorted.length <= classes) {
    return sorted.slice(1).filter((value, index) => value !== sorted[index])
  }
  const breaks: number[] = []
  for (let i = 1; i < classes; i++) {
    // The index is bounded by construction (i < classes < sorted.length), so the
    // read is always in range.
    const value = sorted[Math.floor((i / classes) * sorted.length)]
    if (value !== breaks[breaks.length - 1]) breaks.push(value)
  }
  return breaks
}

/** Class index for a value given ascending breaks. */
export function classIndexFor(value: number, breaks: number[]): number {
  let index = 0
  while (index < breaks.length && value >= breaks[index]) index++
  return index
}
