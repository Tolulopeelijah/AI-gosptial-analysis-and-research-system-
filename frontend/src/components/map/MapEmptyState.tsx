import { AgentIcon } from '@/components/ui/Icons'

/**
 * The intentional empty state.
 *
 * Shown before anything has been asked. It sits over the live map (which stays
 * pannable and zoomable underneath) and states what the surface is for, in the
 * tool's own vocabulary — no hero copy, no illustration.
 */
export function MapEmptyState() {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
      <div className="pointer-events-auto w-full max-w-md overflow-hidden rounded-[3px] border border-line-strong bg-panel/96 shadow-[0_6px_24px_rgb(11_11_11/0.10)] backdrop-blur-[2px]">
        <div className="h-1 bg-gradient-to-r from-accent via-[#1baf7a] to-accent" aria-hidden="true" />
        <div className="px-5 py-4">
          <div className="flex items-center gap-2 text-ink-2">
            <AgentIcon size={16} />
            <h2 className="text-[15px] font-bold tracking-[-0.01em] text-ink">
              Ask a question about the geographic data
            </h2>
          </div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">
            The agent resolves the request into datasets and GIS operations — septic
            systems, floodplains, Maumee water quality, NCWQR research — then draws
            the result here.
          </p>
        </div>
      </div>
    </div>
  )
}
