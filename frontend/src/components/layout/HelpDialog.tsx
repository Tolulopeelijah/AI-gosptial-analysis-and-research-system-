import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { CAPABILITY_NOTES, SHORTCUTS } from '@/data/app'
import {
  DEMO_ERROR_PATHS,
  EXAMPLE_QUERIES,
  EXAMPLE_TIER_LABELS,
  EXAMPLE_TIER_ORDER,
} from '@/data/scenarios'
import { useQueryState } from '@/state/QueryProvider'
import { BACKEND_ENDPOINT } from '@/services/geospatialApi'
import { Button, IconButton } from '@/components/ui/Button'
import { StatusBadge } from '@/components/ui/Panel'
import { XIcon } from '@/components/ui/Icons'

/**
 * Help.
 *
 * Written for someone evaluating the prototype: it states what the system does,
 * how to drive it from the keyboard, which example queries to try, and — more
 * usefully — which queries deliberately fail and what each failure is meant to
 * show. Every example and error path is clickable, so the dialog doubles as a
 * test harness for the error states.
 */
export function HelpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { fillDraft } = useQueryState()

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  const run = (text: string) => {
    fillDraft(text)
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-[2000] flex items-start justify-center overflow-y-auto bg-ink/25 p-4 sm:p-8"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Help"
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-2xl rounded-[3px] border border-line-strong bg-panel shadow-[0_12px_40px_rgb(11_11_11/0.20)]"
      >
        <header className="flex h-10 items-center justify-between border-b border-line px-3">
          <h2 className="text-[13px] font-semibold text-ink">How this works</h2>
          <IconButton label="Close help" variant="default" onClick={onClose}>
            <XIcon />
          </IconButton>
        </header>

        <div className="max-h-[70vh] space-y-4 overflow-y-auto p-4">
          <section>
            <p className="text-[12px] leading-relaxed text-ink-2">
              Type a question about the geographic data and the agent resolves it into datasets and
              GIS operations, then draws the result. The map is an output surface — you are not
              expected to draw on it.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <StatusBadge tone="accent">{`Agent backend · ${BACKEND_ENDPOINT}`}</StatusBadge>
              <StatusBadge tone="neutral">Results held in memory only</StatusBadge>
            </div>
          </section>

          <section>
            <Heading>Example queries</Heading>
            <div className="mt-2 space-y-2">
              {EXAMPLE_TIER_ORDER.map((tier) => (
                <div key={tier}>
                  <div className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
                    {EXAMPLE_TIER_LABELS[tier]}
                  </div>
                  <ul className="mt-1 space-y-0.5">
                    {EXAMPLE_QUERIES.filter((example) => example.tier === tier).map((example) => (
                      <li key={example.id}>
                        <button
                          type="button"
                          onClick={() => run(example.text)}
                          className="w-full rounded-[2px] border border-transparent px-2 py-1 text-left hover:border-line hover:bg-panel-muted"
                        >
                          <span className="block text-[12px] text-ink">{example.text}</span>
                          <span className="block text-[11px] text-ink-3">{example.note}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>

          <section>
            <Heading>Failure paths worth trying</Heading>
            <p className="mt-1 text-[11px] leading-snug text-ink-3">
              Each of these is handled as its own case rather than one generic error. Click one to
              load it into the composer.
            </p>
            <ul className="mt-2 divide-y divide-line border border-line">
              {DEMO_ERROR_PATHS.map((path) => (
                <li key={path.query}>
                  <button
                    type="button"
                    onClick={() => run(path.query)}
                    className="flex w-full flex-col gap-0.5 px-2.5 py-1.5 text-left hover:bg-panel-muted sm:flex-row sm:items-baseline sm:justify-between sm:gap-4"
                  >
                    <span className="text-[12px] text-ink">{path.query}</span>
                    <span className="shrink-0 text-[11px] text-ink-3 sm:max-w-[52%] sm:text-right">
                      {path.outcome}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <Heading>Keyboard</Heading>
            <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              {SHORTCUTS.map((shortcut) => (
                <div key={shortcut.keys} className="col-span-2 grid grid-cols-subgrid">
                  <dt>
                    <kbd className="rounded-[2px] border border-line-strong bg-panel-muted px-1.5 py-0.5 font-mono text-[11px] text-ink-2">
                      {shortcut.keys}
                    </kbd>
                  </dt>
                  <dd className="self-center text-[12px] text-ink-2">{shortcut.action}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section>
            <Heading>Scope of this build</Heading>
            <ul className="mt-1.5 space-y-1.5">
              {CAPABILITY_NOTES.map((note) => (
                <li key={note.label} className="text-[12px] leading-snug">
                  <span className="text-ink">{note.label}.</span>{' '}
                  <span className="text-ink-2">{note.detail}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <footer className="flex items-center justify-end border-t border-line px-3 py-2">
          <Button size="sm" onClick={onClose}>
            Close
          </Button>
        </footer>
      </div>
    </div>
  )
}

function Heading({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-2">{children}</h3>
  )
}
