import { HistoryDrawer } from '@/components/history/HistoryDrawer'
import { UploadDrawer } from '@/components/query/UploadDrawer'

/**
 * Slim shortcut rail at the extreme left of the workspace.
 *
 * History (hamburger) on top, dataset upload below it — each opens its own
 * slide-over drawer. A future settings button belongs here too, under the
 * upload button.
 */
export function ActivityRail() {
  return (
    <nav
      aria-label="Workspace shortcuts"
      className="flex shrink-0 flex-row items-center gap-1 border-b border-line bg-panel px-2 py-1.5 lg:w-11 lg:flex-col lg:items-center lg:gap-1 lg:border-b-0 lg:border-r lg:px-0 lg:py-2"
    >
      <HistoryDrawer />
      <UploadDrawer />
      {/* Settings button slot — a future <SettingsButton /> goes here,
          below the upload button in this rail. */}
    </nav>
  )
}
