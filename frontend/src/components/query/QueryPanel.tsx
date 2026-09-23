import { useEffect, useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { useQueryState } from '@/state/QueryProvider'
import { useMapState } from '@/state/MapProvider'
import { Panel } from '@/components/ui/Panel'
import { Button } from '@/components/ui/Button'
import { AgentIcon, SearchIcon, XIcon } from '@/components/ui/Icons'
import { ExampleQueries } from './ExampleQueries'
import { MapContextChip } from './MapContextChip'

const MAX_LENGTH = 500

/**
 * The composer.
 *
 * This is the primary input surface — natural language, not the map. The
 * keyboard contract is the one a person already expects from a search box with
 * multi-line text: Enter runs, Shift+Enter breaks the line.
 *
 * The map's current view is attached to the request as `QueryContext` (see
 * `MapContextChip`), which is the same seam a future drawn polygon would use.
 */
export function QueryPanel() {
  const { draft, setDraft, fillDraft, focusRequest, query } = useQueryState()
  const { run, isRunning, submit, cancel } = query
  const { getBounds, getCenter, getZoom } = useMapState()

  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  // An example query clicked elsewhere in the interface should land in the
  // composer with the caret ready, not just change the text.
  useEffect(() => {
    if (focusRequest === 0) return
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.focus()
    textarea.setSelectionRange(textarea.value.length, textarea.value.length)
  }, [focusRequest])

  const trimmed = draft.trim()
  const canSubmit = trimmed.length > 0 && !isRunning

  function handleSubmit() {
    if (!canSubmit) return
    const bounds = getBounds()
    const center = getCenter()
    const zoom = getZoom()
    submit(trimmed, {
      mapBounds: bounds ?? undefined,
      mapCenter: center ?? undefined,
      mapZoom: zoom ?? undefined,
    })
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter') return
    // Shift+Enter inserts a newline; plain Enter and Ctrl/Cmd+Enter both run.
    if (event.shiftKey) return
    event.preventDefault()
    handleSubmit()
  }

  return (
    <Panel
      title="Query"
      icon={<SearchIcon size={14} />}
      actions={
        run.status === 'failed' ? (
          <button
            type="button"
            onClick={() => fillDraft(run.query)}
            className="text-[11px] text-ink-3 hover:text-ink"
            title="Put the failed query back in the composer"
          >
            restore
          </button>
        ) : null
      }
      className="shrink-0"
    >
      <div className="border border-line-strong bg-panel focus-within:border-accent">
        <label className="sr-only" htmlFor="geoscope-query">
          Ask a question about the geographic data
        </label>
        <textarea
          id="geoscope-query"
          ref={textareaRef}
          value={draft}
          onChange={(event) => setDraft(event.target.value.slice(0, MAX_LENGTH))}
          onKeyDown={handleKeyDown}
          rows={3}
          spellCheck={false}
          placeholder="Find septic systems within 2 km of floodplain areas"
          className="block w-full resize-none bg-transparent px-2.5 py-2 text-[13px] leading-relaxed text-ink outline-none placeholder:text-ink-3"
        />

        <div className="flex items-center justify-between gap-2 border-t border-line px-2 py-1.5">
          <span className="min-w-0 truncate text-[10px] text-ink-3">
            {draft.length > 0 ? (
              <>
                <span className="font-mono tabular-nums">{draft.length}</span>
                <span className="text-ink-3">/{MAX_LENGTH}</span>
                <span className="ml-2">Enter to run · Shift+Enter for a new line</span>
              </>
            ) : (
              <span>Ask in plain language — the map is the answer, not the input</span>
            )}
          </span>

          <div className="flex shrink-0 items-center gap-1.5">
            {isRunning ? (
              <Button size="sm" variant="default" icon={<XIcon size={13} />} onClick={cancel}>
                Cancel
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="primary"
              icon={<AgentIcon size={13} />}
              onClick={handleSubmit}
              disabled={!canSubmit}
              loading={isRunning}
            >
              {isRunning ? 'Running' : 'Run query'}
            </Button>
          </div>
        </div>
      </div>

      <MapContextChip />

      <div className="mt-3">
        <div className="mb-1.5 flex items-baseline justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
            Example queries
          </span>
          <span className="text-[10px] text-ink-3">click to load</span>
        </div>
        <ExampleQueries disabled={isRunning} />
      </div>
    </Panel>
  )
}
