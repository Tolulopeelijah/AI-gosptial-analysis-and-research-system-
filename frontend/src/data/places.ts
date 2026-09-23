import type { LatLng } from '@/types/geospatial'

/**
 * Reference places used by distance queries ("within 50 km of Dallas") and by
 * the map's reference layer.
 *
 * These are city-centre coordinates. A real backend would geocode against a
 * gazetteer; this table exists so the prototype can resolve a named place
 * without a network call. Add entries here to make new places queryable.
 */
export interface Place {
  id: string
  name: string
  state: string
  stateFips: string
  center: LatLng
  /** Alternative spellings matched by the query parser. */
  aliases?: string[]
}

export const PLACES: Place[] = [
  // Texas
  { id: 'dallas-tx', name: 'Dallas', state: 'Texas', stateFips: '48', center: { lat: 32.7767, lng: -96.797 } },
  { id: 'fort-worth-tx', name: 'Fort Worth', state: 'Texas', stateFips: '48', center: { lat: 32.7555, lng: -97.3308 }, aliases: ['fort worth'] },
  { id: 'houston-tx', name: 'Houston', state: 'Texas', stateFips: '48', center: { lat: 29.7604, lng: -95.3698 } },
  { id: 'austin-tx', name: 'Austin', state: 'Texas', stateFips: '48', center: { lat: 30.2672, lng: -97.7431 } },
  { id: 'san-antonio-tx', name: 'San Antonio', state: 'Texas', stateFips: '48', center: { lat: 29.4241, lng: -98.4936 }, aliases: ['san antonio'] },
  { id: 'el-paso-tx', name: 'El Paso', state: 'Texas', stateFips: '48', center: { lat: 31.7619, lng: -106.485 } },
  { id: 'lubbock-tx', name: 'Lubbock', state: 'Texas', stateFips: '48', center: { lat: 33.5779, lng: -101.8552 } },
  { id: 'amarillo-tx', name: 'Amarillo', state: 'Texas', stateFips: '48', center: { lat: 35.222, lng: -101.8313 } },

  // California
  { id: 'los-angeles-ca', name: 'Los Angeles', state: 'California', stateFips: '06', center: { lat: 34.0522, lng: -118.2437 }, aliases: ['la'] },
  { id: 'san-francisco-ca', name: 'San Francisco', state: 'California', stateFips: '06', center: { lat: 37.7749, lng: -122.4194 }, aliases: ['sf'] },
  { id: 'san-diego-ca', name: 'San Diego', state: 'California', stateFips: '06', center: { lat: 32.7157, lng: -117.1611 } },
  { id: 'sacramento-ca', name: 'Sacramento', state: 'California', stateFips: '06', center: { lat: 38.5816, lng: -121.4944 } },
  { id: 'fresno-ca', name: 'Fresno', state: 'California', stateFips: '06', center: { lat: 36.7378, lng: -119.7871 } },
  { id: 'san-jose-ca', name: 'San Jose', state: 'California', stateFips: '06', center: { lat: 37.3382, lng: -121.8863 } },

  // Oklahoma
  { id: 'oklahoma-city-ok', name: 'Oklahoma City', state: 'Oklahoma', stateFips: '40', center: { lat: 35.4676, lng: -97.5164 } },
  { id: 'tulsa-ok', name: 'Tulsa', state: 'Oklahoma', stateFips: '40', center: { lat: 36.154, lng: -95.9928 } },

  // New Mexico
  { id: 'albuquerque-nm', name: 'Albuquerque', state: 'New Mexico', stateFips: '35', center: { lat: 35.0844, lng: -106.6504 } },
  { id: 'santa-fe-nm', name: 'Santa Fe', state: 'New Mexico', stateFips: '35', center: { lat: 35.687, lng: -105.9378 } },

  // Louisiana
  { id: 'new-orleans-la', name: 'New Orleans', state: 'Louisiana', stateFips: '22', center: { lat: 29.9511, lng: -90.0715 } },
  { id: 'baton-rouge-la', name: 'Baton Rouge', state: 'Louisiana', stateFips: '22', center: { lat: 30.4515, lng: -91.1871 } },

  // Arkansas
  { id: 'little-rock-ar', name: 'Little Rock', state: 'Arkansas', stateFips: '05', center: { lat: 34.7465, lng: -92.2896 } },
]

/** Case-insensitive, longest-name-first lookup so "Fort Worth" beats "Worth". */
export function findPlaceByName(raw: string): Place | null {
  const needle = raw.trim().toLowerCase().replace(/\s+/g, ' ')
  if (!needle) return null
  let best: Place | null = null
  for (const place of PLACES) {
    const candidates = [place.name, ...(place.aliases ?? [])]
    for (const candidate of candidates) {
      if (candidate.toLowerCase() === needle) {
        if (!best || candidate.length > best.name.length) best = place
      }
    }
  }
  return best
}

/** Finds a place mentioned anywhere in a free-text query. */
export function findPlaceInQuery(query: string): Place | null {
  const haystack = ` ${query.toLowerCase()} `
  const matches: Array<{ place: Place; term: string }> = []
  for (const place of PLACES) {
    for (const candidate of [place.name, ...(place.aliases ?? [])]) {
      const term = candidate.toLowerCase()
      // Word-boundary match so the "la" alias doesn't fire inside "land".
      const pattern = new RegExp(`(^|[^a-z])${escapeRegExp(term)}([^a-z]|$)`)
      if (pattern.test(haystack)) {
        matches.push({ place, term })
        break
      }
    }
  }
  if (matches.length === 0) return null
  // Longest mention wins: "Fort Worth" beats a bare "Worth" style collision.
  matches.sort((a, b) => b.term.length - a.term.length)
  return matches[0].place
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
