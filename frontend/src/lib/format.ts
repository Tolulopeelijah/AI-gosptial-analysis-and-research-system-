/** Presentation helpers shared by the panels. */

/** 1234567 -> "1,234,567" */
export function formatCount(value: number): string {
  return new Intl.NumberFormat('en-US').format(Math.round(value))
}

/**
 * Compact form for stat tiles: 1,284 / 12.9K / 4.2M.
 * Below 10,000 the exact number is more useful than the abbreviation.
 */
export function formatCompact(value: number): string {
  const abs = Math.abs(value)
  if (abs < 10_000) return formatCount(value)
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

export function formatNumber(value: number, precision?: number): string {
  if (!Number.isFinite(value)) return '—'
  if (precision != null) {
    return new Intl.NumberFormat('en-US', {
      minimumFractionDigits: precision,
      maximumFractionDigits: precision,
    }).format(value)
  }
  if (Number.isInteger(value)) return formatCount(value)
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value)
}

export function formatAttributeValue(value: unknown, precision?: number): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'number') return formatNumber(value, precision)
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

/** Relative for recent items, absolute once "3 days ago" stops being useful. */
export function formatRelativeTime(timestamp: number, now = Date.now()): string {
  const deltaMs = now - timestamp
  const seconds = Math.round(deltaMs / 1000)
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days} d ago`
  return new Date(timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function formatClockTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function formatDuration(ms: number | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`
}

/** "32.777°N 96.797°W" — the coordinate readout convention for the map. */
export function formatLatLng(lat: number, lng: number, precision = 3): string {
  const latLabel = `${Math.abs(lat).toFixed(precision)}°${lat >= 0 ? 'N' : 'S'}`
  const lngLabel = `${Math.abs(lng).toFixed(precision)}°${lng >= 0 ? 'E' : 'W'}`
  return `${latLabel} ${lngLabel}`
}

/** "32.7767, -96.7970" — copy-pasteable form. */
export function formatCoordinates(lat: number, lng: number, precision = 5): string {
  return `${lat.toFixed(precision)}, ${lng.toFixed(precision)}`
}

/** Short, quotable form of a query for history rows and headings. */
export function truncate(text: string, max = 120): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length <= max ? clean : `${clean.slice(0, max - 1).trimEnd()}…`
}

/** "Texas" for state FIPS 48, used for short state labels. */
const STATE_NAMES: Record<string, string> = {
  '05': 'Arkansas',
  '06': 'California',
  '22': 'Louisiana',
  '35': 'New Mexico',
  '40': 'Oklahoma',
  '48': 'Texas',
}

export function stateNameFromFips(stateFips: string): string {
  return STATE_NAMES[stateFips] ?? stateFips
}

export function knownStateNames(): string[] {
  return Object.values(STATE_NAMES).sort()
}
