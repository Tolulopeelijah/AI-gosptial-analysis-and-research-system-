import type { FeatureCollection } from 'geojson'
import type { GeographicResult, TableResult } from '@/types/geospatial'

/** Client-side file download: the backend already returned the bytes. */
function saveBlob(filename: string, mime: string, text: string) {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
}

function cell(value: string | number | boolean | null): string {
  if (value == null) return ''
  const text = String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function downloadTableCsv(table: TableResult) {
  const lines = [
    table.columns.map(cell).join(','),
    ...table.rows.map((row) => table.columns.map((column) => cell(row[column] ?? null)).join(',')),
  ]
  saveBlob(`${slug(table.title || table.id) || 'table'}.csv`, 'text/csv', lines.join('\n'))
}

export function downloadLayerGeoJson(result: GeographicResult) {
  const collection: FeatureCollection = {
    type: 'FeatureCollection',
    features: Array.isArray((result.data as FeatureCollection).features)
      ? (result.data as FeatureCollection).features
      : [],
  }
  saveBlob(
    `${slug(result.metadata?.title ?? result.id) || 'layer'}.geojson`,
    'application/geo+json',
    JSON.stringify(collection),
  )
}
