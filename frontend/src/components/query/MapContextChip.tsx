import { TargetIcon } from '@/components/ui/Icons'

/**
 * Explains what the composer attaches to a request.
 *
 * The map's current view travels with every query as `QueryContext` — the
 * same field a drawn polygon or selected feature would populate.
 */
export function MapContextChip() {
  return (
    <div
      className="mt-2 flex items-start gap-1.5 border border-line bg-panel-muted px-2 py-1.5"
      title="QueryContext in src/types/geospatial.ts"
    >
      <TargetIcon size={12} className="mt-[3px] shrink-0 text-ink-3" />
      <p className="text-[11px] leading-snug text-ink-2">
        <span className="text-ink">Map view attached.</span> Bounds, centre and zoom travel with
        each request — the same field a drawn polygon or selected feature would fill.
      </p>
    </div>
  )
}
