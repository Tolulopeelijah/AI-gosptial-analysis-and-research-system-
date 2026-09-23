import { useMemo, useState } from 'react'
import { cn } from '@/lib/cn'
import { resolveAttributeFields } from '@/lib/resultStyle'
import { formatAttributeValue } from '@/lib/format'
import { toFeatures } from '@/lib/geo'
import { useMapState } from '@/state/MapProvider'
import { ChevronDownIcon, ChevronRightIcon } from '@/components/ui/Icons'
import type { Feature } from 'geojson'
import type { AttributeField, GeographicResult } from '@/types/geospatial'

const PREVIEW_ROWS = 25

/**
 * Attribute table for a result layer.
 *
 * The columns come from the backend's declared `attributes` when it supplies
 * them, and are inferred from the first feature's properties otherwise — so a
 * backend that has not been taught to declare fields still gets a usable table.
 * Sorting is client-side over the returned page of features, which is all a
 * preview needs.
 */
export function AttributeTable({ result }: { result: GeographicResult }) {
  const { fitResults } = useMapState()
  const [expanded, setExpanded] = useState(false)
  const [sort, setSort] = useState<{ key: string; direction: 'asc' | 'desc' } | null>(null)

  const fields = useMemo(() => resolveAttributeFields(result), [result])
  const features = useMemo(() => toFeatures(result.data), [result.data])

  const sorted = useMemo(() => {
    if (!sort) return features
    const factor = sort.direction === 'asc' ? 1 : -1
    return [...features].sort((a, b) => factor * compareValues(a, b, sort.key))
  }, [features, sort])

  if (fields.length === 0 || features.length === 0) return null

  const rows = expanded ? sorted : sorted.slice(0, PREVIEW_ROWS)

  function toggleSort(field: AttributeField) {
    setSort((current) => {
      if (!current || current.key !== field.key) return { key: field.key, direction: 'asc' }
      if (current.direction === 'asc') return { key: field.key, direction: 'desc' }
      return null
    })
  }

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
          Attributes
        </span>
        <span className="flex items-center gap-2">
          <span className="font-mono text-[10px] tabular-nums text-ink-3">
            {rows.length}/{features.length}
          </span>
          <button
            type="button"
            onClick={fitResults}
            className="text-[11px] text-ink-3 hover:text-ink"
            title="Zoom the map to this result"
          >
            zoom to
          </button>
        </span>
      </div>

      <div className="max-h-56 overflow-auto border border-line">
        <table className="w-full border-collapse text-[11px]">
          <thead className="sticky top-0 z-10 bg-panel-sunken">
            <tr>
              {fields.map((field) => {
                const isSorted = sort?.key === field.key
                return (
                  <th
                    key={field.key}
                    scope="col"
                    className={cn(
                      'border-b border-line px-2 py-1 font-medium whitespace-nowrap',
                      field.type === 'number' ? 'text-right' : 'text-left',
                      'text-ink-2',
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(field)}
                      className={cn(
                        'inline-flex items-center gap-1 hover:text-ink',
                        field.type === 'number' && 'flex-row-reverse',
                      )}
                      title={`Sort by ${field.label}`}
                    >
                      <span>{field.label}</span>
                      {isSorted ? (
                        <ChevronDownIcon
                          size={11}
                          className={cn(sort?.direction === 'desc' && 'rotate-180')}
                        />
                      ) : null}
                    </button>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((feature, index) => {
              const properties = readProperties(feature)
              return (
                <tr
                  key={feature.id != null ? String(feature.id) : index}
                  className="odd:bg-panel even:bg-panel-muted/45"
                >
                  {fields.map((field) => (
                    <td
                      key={field.key}
                      className={cn(
                        'border-b border-line/70 px-2 py-[3px] whitespace-nowrap text-ink',
                        field.type === 'number' && 'text-right font-mono tabular-nums',
                      )}
                    >
                      {formatAttributeValue(properties[field.key], field.precision)}
                      {field.unit && properties[field.key] != null ? (
                        <span className="ml-0.5 text-ink-3">{field.unit}</span>
                      ) : null}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {features.length > PREVIEW_ROWS ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-1 inline-flex items-center gap-1 text-[11px] text-ink-3 hover:text-ink"
        >
          {expanded ? <ChevronDownIcon size={12} /> : <ChevronRightIcon size={12} />}
          {expanded ? 'Show first 25' : `Show all ${features.length} rows`}
        </button>
      ) : null}
    </div>
  )
}

/**
 * Feature properties as a plain record.
 *
 * `Feature['properties']` is `{ [name: string]: any } | null`, and that union
 * cannot be indexed with a dynamic key — so it is normalised once here.
 */
function readProperties(feature: Feature): Record<string, unknown> {
  const properties = feature.properties
  return properties ? (properties as Record<string, unknown>) : {}
}

function compareValues(a: Feature, b: Feature, key: string): number {
  const left = readProperties(a)[key]
  const right = readProperties(b)[key]
  if (left == null && right == null) return 0
  if (left == null) return -1
  if (right == null) return 1
  if (typeof left === 'number' && typeof right === 'number') return left - right
  return String(left).localeCompare(String(right), 'en', { numeric: true })
}
