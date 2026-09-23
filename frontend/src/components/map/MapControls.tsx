import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { useMapState } from '@/state/MapProvider'
import { IconButton } from '@/components/ui/Button'
import {
  CollapseIcon,
  ExpandIcon,
  GlobeIcon,
  LabelIcon,
  LayersIcon,
  MinusIcon,
  PlusIcon,
  TargetIcon,
} from '@/components/ui/Icons'

/**
 * Map controls.
 *
 * Unobtrusive by design: a single narrow column of icon buttons, grouped by
 * what they act on (view / layers / window) with hairline separators. Every
 * button has a tooltip and an aria-label, and the toggle buttons report
 * `aria-pressed`.
 */
export function MapControls() {
  const {
    zoomIn,
    zoomOut,
    resetView,
    fitResults,
    toggleFullscreen,
    hasResults,
    preferences,
    toggleLayer,
    isFullscreen,
  } = useMapState()

  const resultsAvailable = hasResults()

  return (
    <div className="pointer-events-auto absolute right-3 top-3 flex flex-col overflow-hidden rounded-[3px] border border-line-strong bg-panel/95 shadow-[0_2px_10px_rgb(11_11_11/0.08)] backdrop-blur-[2px]">
      <ControlGroup>
        <IconButton label="Zoom in" onClick={zoomIn}>
          <PlusIcon />
        </IconButton>
        <IconButton label="Zoom out" onClick={zoomOut}>
          <MinusIcon />
        </IconButton>
      </ControlGroup>

      <ControlGroup>
        <IconButton label="Reset view" onClick={resetView}>
          <GlobeIcon />
        </IconButton>
        <IconButton
          label={resultsAvailable ? 'Fit results' : 'No results to fit'}
          onClick={fitResults}
          disabled={!resultsAvailable}
        >
          <TargetIcon />
        </IconButton>
      </ControlGroup>

      <ControlGroup>
        <IconButton
          label="Toggle result layer"
          onClick={() => toggleLayer('results')}
          active={preferences.visibility.results}
          disabled={!resultsAvailable}
        >
          <LayersIcon />
        </IconButton>
        <IconButton
          label="Toggle county labels"
          onClick={() => toggleLayer('labels')}
          active={preferences.visibility.labels}
          disabled={!resultsAvailable}
        >
          <LabelIcon />
        </IconButton>
      </ControlGroup>

      <ControlGroup last>
        <IconButton
          label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
          onClick={toggleFullscreen}
        >
          {isFullscreen ? <CollapseIcon /> : <ExpandIcon />}
        </IconButton>
      </ControlGroup>
    </div>
  )
}

function ControlGroup({ children, last = false }: { children: ReactNode; last?: boolean }) {
  return (
    <div className={cn('flex flex-col p-0.5', !last && 'border-b border-line')}>{children}</div>
  )
}
