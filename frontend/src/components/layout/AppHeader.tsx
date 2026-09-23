import { useState } from 'react'
import { BACKEND_ENDPOINT } from '@/services/geospatialApi'
import { APP_DESCRIPTOR, APP_NAME } from '@/data/app'
import { IconButton } from '@/components/ui/Button'
import { HelpIcon } from '@/components/ui/Icons'
import { StatusIndicator } from './StatusIndicator'
import { SettingsPopover } from './SettingsPopover'
import { HelpDialog } from './HelpDialog'

/**
 * Application header.
 *
 * Compact by design: identity on the left, state and controls on the right.
 * Nothing here competes with the map.
 */
export function AppHeader() {
  const [helpOpen, setHelpOpen] = useState(false)

  return (
    <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-line bg-panel px-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <span
          className="flex size-6 shrink-0 items-center justify-center rounded-[3px] bg-ink text-panel"
          aria-hidden="true"
        >
          <MarkIcon />
        </span>
        <div className="flex min-w-0 items-baseline gap-2">
          <h1 className="truncate text-[14px] font-semibold tracking-[-0.01em] text-ink">
            {APP_NAME}
          </h1>
          <span className="hidden truncate text-[12px] text-ink-3 sm:inline">{APP_DESCRIPTOR}</span>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <StatusIndicator />
        <span className="hidden font-mono text-[10px] text-ink-3 lg:inline" title="Agent backend">
          {BACKEND_ENDPOINT}
        </span>
        <div className="relative">
          <SettingsPopover />
        </div>
        <IconButton
          label="Help and examples"
          variant="default"
          active={helpOpen}
          onClick={() => setHelpOpen(true)}
        >
          <HelpIcon />
        </IconButton>
      </div>

      <HelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
    </header>
  )
}

/** A small surveyor's mark: three nested squares, drawn in the panel colour. */
function MarkIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="14" height="14" stroke="currentColor" strokeWidth="1.4" />
      <rect x="4.5" y="4.5" width="7" height="7" stroke="currentColor" strokeWidth="1.2" />
      <path d="M8 4.5V2M8 14v-2.5M4.5 8H2M14 8h-2.5" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  )
}
