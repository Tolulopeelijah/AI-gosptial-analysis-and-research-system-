import { useCallback, useEffect, useState } from 'react'
import { BACKEND_ENDPOINT } from '@/services/geospatialApi'
import { Panel } from '@/components/ui/Panel'
import { Button, IconButton } from '@/components/ui/Button'
import { DatabaseIcon, TrashIcon, UploadIcon } from '@/components/ui/Icons'
import type { DatasetEntry } from '@/types/geospatial'

/**
 * User datasets: upload a file, see what's registered, remove it.
 *
 * CSV (with latitude/longitude columns), GeoJSON, and XLSX are accepted.
 * Uploaded point/geometry layers become queryable by name like any built-in
 * dataset (e.g. "Show my wells dataset"); tabular files answer table
 * questions. Coordinates are assumed EPSG:4326 — stated on each entry.
 */
export function DataUpload() {
  const [entries, setEntries] = useState<DatasetEntry[] | null>(null)
  const [uploading, setUploading] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`${BACKEND_ENDPOINT}/api/datasets`)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const payload = (await response.json()) as { datasets?: DatasetEntry[] }
      setEntries(payload.datasets ?? [])
    } catch {
      setEntries(null)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function handleFile(file: File | undefined) {
    if (!file) return
    setUploading(true)
    setNotice(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const response = await fetch(`${BACKEND_ENDPOINT}/api/datasets/upload`, {
        method: 'POST',
        body: form,
      })
      const payload = (await response.json()) as { ok?: boolean; error?: string }
      if (!response.ok || !payload.ok) throw new Error(payload.error ?? `HTTP ${response.status}`)
      setNotice(`Registered “${file.name}” — ask about it by name.`)
      await refresh()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete(name: string) {
    try {
      const response = await fetch(`${BACKEND_ENDPOINT}/api/datasets/${name}`, {
        method: 'DELETE',
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await refresh()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Delete failed.')
    }
  }

  const uploads = (entries ?? []).filter((entry) => entry.source_type === 'user_upload')

  return (
    <Panel
      title="Your datasets"
      icon={<DatabaseIcon size={14} />}
      className="shrink-0"
      actions={
        <span className="font-mono text-[10px] tabular-nums text-ink-3">
          {uploads.length} file{uploads.length === 1 ? '' : 's'}
        </span>
      }
    >
      <label
        className={
          'flex cursor-pointer items-center justify-center gap-2 border border-dashed border-line-strong px-2 py-2 text-[12px] text-ink-2 hover:border-accent hover:text-ink' +
          (uploading ? ' pointer-events-none opacity-60' : '')
        }
      >
        <UploadIcon size={13} />
        {uploading ? 'Uploading…' : 'Upload CSV, GeoJSON, or XLSX'}
        <input
          type="file"
          accept=".csv,.geojson,.json,.xlsx,.xls"
          className="sr-only"
          disabled={uploading}
          onChange={(event) => {
            void handleFile(event.target.files?.[0])
            event.target.value = ''
          }}
        />
      </label>

      {notice ? <p className="mt-1.5 text-[11px] leading-snug text-ink-2">{notice}</p> : null}

      {uploads.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {uploads.map((entry) => (
            <li
              key={entry.name}
              className="flex items-center justify-between gap-2 border border-line px-2 py-1.5"
            >
              <span className="min-w-0">
                <span className="block truncate text-[12px] font-medium text-ink">
                  {entry.name}
                </span>
                <span className="block truncate text-[10px] text-ink-3">
                  {entry.description}
                </span>
              </span>
              <IconButton
                label={`Remove ${entry.name}`}
                variant="default"
                onClick={() => void handleDelete(entry.name)}
              >
                <TrashIcon size={12} />
              </IconButton>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1.5 text-[11px] leading-snug text-ink-3">
          No files yet. Uploaded layers are queried by name in any mode.
        </p>
      )}
      <div className="mt-2">
        <Button size="sm" variant="ghost" fullWidth onClick={() => void refresh()}>
          Refresh list
        </Button>
      </div>
    </Panel>
  )
}
