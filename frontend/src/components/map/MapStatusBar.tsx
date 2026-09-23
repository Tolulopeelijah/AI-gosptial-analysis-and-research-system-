import { PLACES } from '@/data/places'
import { useMapState } from '@/state/MapProvider'
import { formatLatLng } from '@/lib/format'
import { XIcon } from '@/components/ui/Icons'
import type { LatLng } from '@/types/geospatial'

/**
 * Coordinate and layer readout.
 *
 * A GIS surface should always be able to answer "where am I and what is
 * shown?". Clicking the map drops a coordinate read-out here — the first half
 * of map input; sending those coordinates to the backend as query context is
 * the next step and needs no new plumbing (see `QueryContext`).
 */
export function MapStatusBar({
  zoom,
  center,
  picked,
  featureCount,
  datasetLabel,
  onClearPicked,
}: {
  zoom: number
  center: LatLng
  picked: LatLng | null
  featureCount: number
  datasetLabel?: string
  onClearPicked: () => void
}) {
  const { preferences } = useMapState()
  const placesCount = preferences.visibility.places ? PLACES.length : 0

  return (
    <div className="absolute left-3 top-3 flex max-w-[calc(100%-6rem)] flex-col items-start gap-1">
      <div className="pointer-events-auto flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[3px] border border-line-strong bg-panel/95 px-2.5 py-1 font-mono text-[11px] tabular-nums text-ink-2 shadow-[0_2px_10px_rgb(11_11_11/0.06)] backdrop-blur-[2px]">
        <Readout label="zoom" value={zoom.toFixed(1)} />
        <Readout label="center" value={formatLatLng(center.lat, center.lng, 2)} />
        <Readout label="features" value={String(featureCount)} />
        {placesCount > 0 ? <Readout label="ref places" value={String(placesCount)} /> : null}
        {datasetLabel ? (
          <span className="hidden max-w-[22ch] truncate text-ink-3 xl:inline" title={datasetLabel}>
            {datasetLabel}
          </span>
        ) : null}
      </div>

      {picked ? (
        <div className="pointer-events-auto flex items-center gap-2 rounded-[3px] border border-accent/40 bg-accent-soft/50 px-2.5 py-1 font-mono text-[11px] tabular-nums text-accent-ink shadow-[0_2px_10px_rgb(11_11_11/0.06)]">
          <span className="text-ink-2">picked</span>
          <span>
            {picked.lat.toFixed(5)}, {picked.lng.toFixed(5)}
          </span>
          <button
            type="button"
            className="text-ink-3 hover:text-ink"
            aria-label="Clear picked coordinate"
            onClick={onClearPicked}
          >
            <XIcon size={12} />
          </button>
        </div>
      ) : (
        <span className="pointer-events-none rounded-[2px] bg-panel/80 px-1.5 text-[10px] text-ink-3">
          click the map to read coordinates
        </span>
      )}
    </div>
  )
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <span className="whitespace-nowrap">
      <span className="text-ink-3">{label} </span>
      <span className="text-ink">{value}</span>
    </span>
  )
}
