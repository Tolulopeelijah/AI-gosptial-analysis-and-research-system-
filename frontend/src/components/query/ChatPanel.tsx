import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useQueryState } from '@/state/QueryProvider'
import { useMapState } from '@/state/MapProvider'
import { Panel } from '@/components/ui/Panel'
import { Button, IconButton } from '@/components/ui/Button'
import { AgentIcon, ChatIcon, UploadIcon, XIcon } from '@/components/ui/Icons'
import { RichText } from '@/components/results/RichText'

const MAX_LENGTH = 500

/**
 * Conversational Q&A.
 *
 * A thread of turns (question + answer) with a composer pinned at the bottom.
 * Each turn still runs the agent pipeline; previous turns travel as history so
 * follow-ups ("what about nitrogen?") resolve. This panel is deliberately
 * roomy — large type, example prompts, one-tap send — because chat is where
 * non-technical users spend their time.
 */
export function ChatPanel() {
  const { draft, setDraft, chatTurns, chatHistory, clearChat, requestUpload, query } =
    useQueryState()
  const { run, isRunning, submit, cancel } = query
  const { getBounds, getCenter, getZoom } = useMapState()
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [chatTurns.length, isRunning])

  // Seed the input from shared examples without leaving chat mode.
  useEffect(() => {
    if (draft) {
      setInput(draft)
      setDraft('')
    }
  }, [draft, setDraft])

  function handleSend() {
    const trimmed = input.trim()
    if (!trimmed || isRunning) return
    submit(
      trimmed,
      {
        mapBounds: getBounds() ?? undefined,
        mapCenter: getCenter() ?? undefined,
        mapZoom: getZoom() ?? undefined,
      },
      { mode: 'chat', history: chatHistory },
    )
    setInput('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey) return
    event.preventDefault()
    handleSend()
  }

  return (
    <Panel
      title="Ask WIES"
      icon={<ChatIcon size={14} />}
      actions={
        chatTurns.length > 0 ? (
          <button
            type="button"
            onClick={clearChat}
            className="text-[11px] text-ink-3 hover:text-ink"
            title="Clear the conversation"
          >
            clear
          </button>
        ) : null
      }
      className="flex min-h-0 flex-1 flex-col"
    >
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-0.5">
        {chatTurns.length === 0 && !isRunning ? (
          <div className="space-y-2.5">
            <p className="text-[16px] font-semibold leading-snug text-ink">
              Ask in plain English
            </p>
            <p className="text-[13.5px] leading-relaxed text-ink-2">
              No technical terms needed — ask about septic systems, floodplains,
              Maumee water quality, or research, just like texting a colleague.
            </p>
            <p className="text-[13px] leading-relaxed text-ink-2">
              Follow-ups remember the thread, so you can ask
              <span className="text-ink"> “what about nitrogen?” </span>
              after a phosphorus answer.
            </p>
          </div>
        ) : null}
        {chatTurns.map((turn, index) => (
          <div key={`${index}-${turn.query.slice(0, 24)}`} className="space-y-2">
            <div className="flex justify-end">
              <p className="max-w-[88%] rounded-[8px] rounded-br-[2px] bg-accent px-3.5 py-2.5 text-[14px] font-medium leading-relaxed text-white">
                {turn.query}
              </p>
            </div>
            <div className="flex items-center gap-1.5 px-0.5">
              <span className="flex size-4 items-center justify-center rounded-full bg-ink text-[8px] font-bold text-panel">
                W
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
                WIES
              </span>
            </div>
            <div className="rounded-[8px] rounded-tl-[2px] border border-line bg-panel px-3.5 py-2.5">
              <p className="whitespace-pre-line text-[14px] leading-relaxed text-ink">
                <RichText
                  text={turn.answer}
                  references={turn.references}
                  idPrefix={`chat-${index}`}
                />
              </p>
              {turn.layers && turn.layers.length > 0 ? (
                <div className="mt-2 border-t border-line pt-2">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-3">
                    Results
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {turn.layers.map((layer, layerIndex) => (
                      <li
                        key={`${layerIndex}-${layer.title}`}
                        className="flex items-baseline justify-between gap-2 text-[13px]"
                      >
                        <span className="min-w-0 truncate text-ink-2">
                          {(layer.dataset ?? layer.title).replace(/_/g, ' ')}
                        </span>
                        <span className="shrink-0 font-mono tabular-nums text-ink">
                          {layer.count}
                        </span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-1 text-[11px] text-ink-3">Shown on the map.</p>
                </div>
              ) : null}
              {turn.references && turn.references.length > 0 ? (
                <ol className="mt-2 space-y-1 border-t border-line pt-2">
                  {turn.references.map((reference) => (
                    <li
                      key={reference.ref}
                      id={`chat-${index}-ref-${reference.ref}`}
                      className="flex scroll-mt-2 items-baseline gap-1.5 text-[12px] leading-snug"
                    >
                      <span className="shrink-0 font-mono text-[11px] text-ink-3">
                        [{reference.ref}]
                      </span>
                      <span className="min-w-0 text-ink-2">
                        {reference.title ?? reference.identifier ?? reference.source}
                        {reference.url ? (
                          <>
                            {' '}
                            <a
                              href={reference.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-accent-ink underline decoration-accent/50 underline-offset-2 hover:decoration-accent"
                              title={reference.identifier ?? reference.url}
                            >
                              {reference.identifier?.startsWith('doi:') ? 'DOI' : 'link'}
                            </a>
                          </>
                        ) : null}
                      </span>
                    </li>
                  ))}
                </ol>
              ) : null}
              {turn.errorCode ? (
                <p className="mt-1 text-[12px] font-medium text-critical">
                  Couldn’t answer that — try rephrasing, or pick an example above.
                </p>
              ) : null}
            </div>
          </div>
        ))}
        {isRunning ? (
          <p className="flex items-center gap-1.5 px-0.5 text-[13px] text-ink-3">
            <span className="size-1.5 animate-pulse rounded-full bg-accent" />
            {run.query ? 'Answering…' : 'Thinking…'}
          </p>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <div className="mt-3 shrink-0 border border-line-strong bg-panel focus-within:border-accent">
        <label className="sr-only" htmlFor="wies-chat">
          Chat message
        </label>
        <textarea
          id="wies-chat"
          value={input}
          onChange={(event) => setInput(event.target.value.slice(0, MAX_LENGTH))}
          onKeyDown={handleKeyDown}
          rows={3}
          spellCheck={false}
          placeholder='Try: "Septic systems near floodplains"…'
          className="block w-full resize-none bg-transparent px-3 py-2.5 text-[14px] leading-relaxed text-ink outline-none placeholder:text-ink-3"
        />
        <div className="flex items-center justify-between gap-1.5 border-t border-line px-2 py-1.5">
          <span className="hidden px-1 text-[11px] text-ink-3 sm:inline">
            Enter to send · Shift+Enter for a new line
          </span>
          <div className="flex items-center gap-1.5">
            <IconButton
              label="Upload a dataset"
              variant="default"
              onClick={requestUpload}
              title="Upload a dataset (CSV, GeoJSON, XLSX)"
            >
              <UploadIcon size={13} />
            </IconButton>
            {isRunning ? (
              <Button size="md" variant="default" icon={<XIcon size={13} />} onClick={cancel}>
                Cancel
              </Button>
            ) : null}
            <Button
              size="md"
              variant="primary"
              icon={<AgentIcon size={13} />}
              onClick={handleSend}
              disabled={input.trim().length === 0 || isRunning}
              loading={isRunning}
            >
              Send
            </Button>
          </div>
        </div>
      </div>
    </Panel>
  )
}
