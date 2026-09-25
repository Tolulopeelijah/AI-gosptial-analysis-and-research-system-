import { useQueryState } from '@/state/QueryProvider'
import { Panel } from '@/components/ui/Panel'
import { Button } from '@/components/ui/Button'
import { DatabaseIcon, DownloadIcon, TableIcon } from '@/components/ui/Icons'
import { downloadLayerGeoJson, downloadTableCsv } from '@/lib/download'
import { truncate } from '@/lib/format'
import type { GeographicResult, TableResult } from '@/types/geospatial'

/**
 * Raw data, for download without analysis.
 *
 * Tabular tool outputs render as compact tables with CSV export; primary
 * feature layers get GeoJSON export. This is the heart of data mode, and a
 * useful appendix to every other mode. With `embedded`, the content renders
 * without panel chrome for placement inside another panel.
 */
export function TablesSection({ embedded = false }: { embedded?: boolean }) {
  const { run } = useQueryState().query
  const tables = run.tables ?? []
  const primaryLayers = run.results.filter((result) => result.metadata?.role !== 'context')

  if (tables.length === 0 && primaryLayers.length === 0) return null

  const summary =
    (tables.length > 0 ? `${tables.length} table${tables.length === 1 ? '' : 's'}` : '') +
    (tables.length > 0 && primaryLayers.length > 0 ? ' · ' : '') +
    (primaryLayers.length > 0
      ? `${primaryLayers.length} layer${primaryLayers.length === 1 ? '' : 's'}`
      : '')

  if (embedded) {
    return (
      <div className="space-y-3">
        <TablesContent tables={tables} primaryLayers={primaryLayers} />
      </div>
    )
  }

  return (
    <Panel
      title="Data"
      icon={<DatabaseIcon size={14} />}
      className="shrink-0"
      actions={<span className="text-[10px] text-ink-3">{summary}</span>}
    >
      <TablesContent tables={tables} primaryLayers={primaryLayers} />
    </Panel>
  )
}
function TablesContent({
  tables,
  primaryLayers,
}: {
  tables: TableResult[]
  primaryLayers: GeographicResult[]
}) {
  return (
    <div className="space-y-3">
      {tables.map((table) => (
          <div key={table.id} className="border border-line">
            <div className="flex items-center justify-between gap-2 border-b border-line bg-panel-muted px-2 py-1.5">
              <span className="flex min-w-0 items-center gap-1.5 text-[12px] font-medium text-ink">
                <TableIcon size={12} className="shrink-0 text-ink-3" />
                <span className="truncate">{table.title}</span>
                <span className="shrink-0 font-mono text-[10px] font-normal text-ink-3">
                  {table.row_count} rows{table.truncated ? ' (first 200)' : ''}
                </span>
              </span>
              <Button
                size="sm"
                variant="default"
                icon={<DownloadIcon size={12} />}
                onClick={() => downloadTableCsv(table)}
              >
                CSV
              </Button>
            </div>
            <div className="max-h-48 overflow-auto">
              <table className="w-full border-collapse text-[11px]">
                <thead className="sticky top-0 bg-panel">
                  <tr>
                    {table.columns.map((column) => (
                      <th
                        key={column}
                        className="border-b border-line px-2 py-1 text-left font-medium text-ink-3"
                      >
                        {truncate(column, 32)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.slice(0, 30).map((row, index) => (
                    <tr key={index} className="odd:bg-panel-muted/40">
                      {table.columns.map((column) => (
                        <td key={column} className="border-b border-line/60 px-2 py-1 text-ink-2">
                          {truncate(String(row[column] ?? ''), 40)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}

        {primaryLayers.length > 0 ? (
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
              Layer downloads
            </div>
            <ul className="space-y-1">
              {primaryLayers.map((layer) => (
                <li
                  key={layer.id}
                  className="flex items-center justify-between gap-2 border border-line px-2 py-1.5"
                >
                  <span className="min-w-0 truncate text-[12px] text-ink-2">
                    {layer.metadata?.title ?? layer.id}
                    <span className="ml-1.5 font-mono text-[10px] text-ink-3">
                      {layer.metadata?.count ?? 0} features
                    </span>
                  </span>
                  <Button
                    size="sm"
                    variant="default"
                    icon={<DownloadIcon size={12} />}
                    onClick={() => downloadLayerGeoJson(layer)}
                  >
                    GeoJSON
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
    </div>
  )
}
