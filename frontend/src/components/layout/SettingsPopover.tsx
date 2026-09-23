import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { BASEMAPS, BASEMAP_ORDER } from '@/data/basemaps'
import { useMapState } from '@/state/MapProvider'
import { useDismissable } from '@/hooks/useDismissable'
import { Button, IconButton } from '@/components/ui/Button'
import { StatusBadge } from '@/components/ui/Panel'
import { SlidersIcon } from '@/components/ui/Icons'
import type { BasemapId, LayerVisibility, MapPreferences } from '@/types/map'

/**
 * Map preferences.
 *
 * The trigger and the panel live in the same component so the panel's dismissal
 * handler can be told to ignore the trigger — otherwise clicking the button
 * while the panel is open would dismiss it on pointerdown and immediately
 * reopen it on click.
 */
export function SettingsPopover() {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const ref = useDismissable<HTMLDivElement>(open, () => setOpen(false), {
    ignore: triggerRef,
  })
  const {
    preferences,
    setBasemap,
    setResultOpacity,
    toggleLayer,
    resetPreferences,
    basemap,
  } = useMapState()

  return (
    <>
      <IconButton
        ref={triggerRef}
        label="Settings"
        variant="default"
        active={open}
        onClick={() => setOpen((value) => !value)}
      >
        <SlidersIcon />
      </IconButton>

      {open ? (
        <div
          ref={ref}
          role="dialog"
          aria-label="Map and service settings"
          className="absolute right-0 top-9 z-[1200] w-72 rounded-[3px] border border-line-strong bg-panel shadow-[0_8px_28px_rgb(11_11_11/0.14)]"
        >
          <SettingsBody
            preferences={preferences}
            basemapHasLabels={basemap.hasLabels}
            setBasemap={setBasemap}
            setResultOpacity={setResultOpacity}
            toggleLayer={toggleLayer}
            resetPreferences={resetPreferences}
          />
        </div>
      ) : null}
    </>
  )
}

interface SettingsBodyProps {
  preferences: MapPreferences
  basemapHasLabels: boolean
  setBasemap: (id: BasemapId) => void
  setResultOpacity: (value: number) => void
  toggleLayer: (layer: keyof LayerVisibility) => void
  resetPreferences: () => void
}

function SettingsBody({
  preferences,
  basemapHasLabels,
  setBasemap,
  setResultOpacity,
  toggleLayer,
  resetPreferences,
}: SettingsBodyProps) {
  return (
    <>
      <Section title="Basemap">
        <ul className="space-y-0.5">
          {BASEMAP_ORDER.map((id) => (
            <li key={id}>
              <RadioRow
                checked={preferences.basemap === id}
                onSelect={() => setBasemap(id as BasemapId)}
                label={BASEMAPS[id].name}
                note={BASEMAPS[id].hasLabels ? 'carries place labels' : 'no place labels'}
              />
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Layers">
        <ul className="space-y-1.5">
          <li>
            <SwitchRow
              checked={preferences.visibility.results}
              onChange={() => toggleLayer('results')}
              label="Result layers"
              note="Everything the query returned"
            />
          </li>
          <li>
              <SwitchRow
                checked={preferences.visibility.labels}
                onChange={() => toggleLayer('labels')}
                label="Feature labels"
                note="Shown when zoomed in or few features"
              />
            </li>
            <li>
              <SwitchRow
                checked={preferences.visibility.places}
                onChange={() => toggleLayer('places')}
                label="Reference places"
                note="City markers for orientation"
              />
          </li>
        </ul>
      </Section>

      <Section title="Result opacity">
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={0.15}
            max={1}
            step={0.05}
            value={preferences.resultOpacity}
            onChange={(event) => setResultOpacity(Number(event.target.value))}
            className="h-1 w-full accent-accent"
            aria-label="Result layer opacity"
          />
          <span className="w-9 shrink-0 text-right font-mono text-[11px] tabular-nums text-ink-2">
            {Math.round(preferences.resultOpacity * 100)}%
          </span>
        </div>
        {basemapHasLabels ? (
          <p className="mt-1.5 text-[11px] leading-snug text-ink-3">
            This basemap carries its own labels; lowering opacity helps the result fill read
            through.
          </p>
        ) : null}
      </Section>

      <div className="flex items-center justify-between gap-2 border-t border-line px-3 py-2">
        <StatusBadge tone="neutral">Preferences persist locally</StatusBadge>
        <Button size="sm" variant="default" onClick={resetPreferences}>
          Reset
        </Button>
      </div>
    </>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-b border-line px-3 py-2.5">
      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
        {title}
      </div>
      {children}
    </div>
  )
}

function RadioRow({
  checked,
  onSelect,
  label,
  note,
}: {
  checked: boolean
  onSelect: () => void
  label: string
  note: string
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={checked}
      className={cn(
        'flex w-full items-center gap-2 rounded-[2px] px-1.5 py-1 text-left',
        checked ? 'bg-accent-soft/50' : 'hover:bg-panel-muted',
      )}
    >
      <span
        className={cn(
          'flex size-3 shrink-0 items-center justify-center rounded-full border',
          checked ? 'border-accent' : 'border-line-strong',
        )}
        aria-hidden="true"
      >
        {checked ? <span className="size-1.5 rounded-full bg-accent" /> : null}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12px] text-ink">{label}</span>
        <span className="block truncate text-[10px] text-ink-3">{note}</span>
      </span>
    </button>
  )
}

function SwitchRow({
  checked,
  onChange,
  label,
  note,
}: {
  checked: boolean
  onChange: () => void
  label: string
  note: string
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="min-w-0">
        <span className="block truncate text-[12px] text-ink">{label}</span>
        <span className="block truncate text-[10px] text-ink-3">{note}</span>
      </span>
      <Switch checked={checked} onChange={onChange} label={label} />
    </div>
  )
}

/** A checkbox styled as a switch; the label is always rendered beside it. */
export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean
  onChange: () => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={onChange}
      className={cn(
        'relative inline-flex h-4 w-7 shrink-0 items-center rounded-full border transition-colors',
        checked ? 'border-accent bg-accent' : 'border-line-strong bg-panel-sunken',
        disabled && 'cursor-not-allowed opacity-45',
      )}
    >
      <span
        className={cn(
          'absolute size-2.5 rounded-full bg-panel transition-[left]',
          checked ? 'left-[15px]' : 'left-[3px]',
        )}
        aria-hidden="true"
      />
    </button>
  )
}
