import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useQueryState } from '@/state/QueryProvider'
import { useMapState } from '@/state/MapProvider'
import { Panel } from '@/components/ui/Panel'
import { Button } from '@/components/ui/Button'
import { AgentIcon, ChatIcon, XIcon } from '@/components/ui/Icons'

const MAX_LENGTH = 500

/**
 * Conversational Q&A.
 *
 * A thread of turns (question + answer) with a composer pinned at the bottom.
 * Each turn still runs the agent pipeline; previous turns travel as history so
 * follow-ups ("what about nitrogen?") resolve. The map stays small in this
 * mode — the answer text is the point.
 */
export function ChatPanel() {
  const { draft, setDraft, chatTurns, chatHistory, clearChat, query } = useQueryState()
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
      title="Chat"
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
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-0.5">
        {chatTurns.length === 0 && !isRunning ? (
          <div className="space-y-1.5">
            <p className="text-[13px] font-semibold leading-snug text-ink">
              Chat with your geographic data
            </p>
            <p className="text-[12px] leading-relaxed text-ink-2">
              Ask about septic systems, floodplains, Maumee water quality, or NCWQR
              research — in plain language, just like texting a colleague.
            </p>
            <p className="text-[12px] leading-relaxed text-ink-2">
              Follow-ups remember the thread, so you can ask
              <span className="text-ink"> “what about nitrogen?” </span>
              after a phosphorus answer.
            </p>
          </div>
        ) : null}
        {chatTurns.map((turn, index) => (
          <div key={`${index}-${turn.query.slice(0, 24)}`} className="space-y-1.5">
            <div className="flex justify-end">
              <p className="max-w-[88%] rounded-[6px] rounded-br-[2px] bg-accent px-2.5 py-1.5 text-[12.5px] font-medium leading-snug text-white">
                {turn.query}
              </p>
            </div>
            <div className="flex items-center gap-1.5 px-0.5">
              <span className="flex size-4 items-center justify-center rounded-full bg-ink text-[8px] font-bold text-panel">
                W
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
                WEIS
              </span>
            </div>
            <div className="rounded-[6px] rounded-tl-[2px] border border-line bg-panel px-2.5 py-1.5">
              <p className="text-[12.5px] leading-relaxed text-ink">{turn.answer}</p>
              {turn.references && turn.references.length > 0 ? (
                <p className="mt-1.5 border-t border-line pt-1 font-mono text-[10px] leading-snug text-ink-3">
                  {turn.references.map((reference) => `[${reference.ref}]`).join(' ')}{' '}
                  {turn.references
                    .map((reference) => reference.identifier ?? reference.title)
                    .filter(Boolean)
                    .slice(0, 3)
                    .join(' · ')}
                </p>
              ) : null}
              {turn.errorCode ? (
                <p className="mt-0.5 text-[11px] font-medium text-critical">
                  Couldn’t answer that turn.
                </p>
              ) : null}
            </div>
          </div>
        ))}
        {isRunning ? (
          <p className="flex items-center gap-1.5 px-0.5 text-[12px] text-ink-3">
            <span className="size-1.5 animate-pulse rounded-full bg-accent" />
            {run.query ? 'Answering…' : 'Thinking…'}
          </p>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <div className="mt-2 shrink-0 border border-line-strong bg-panel focus-within:border-accent">
        <label className="sr-only" htmlFor="weis-chat">
          Chat message
        </label>
        <textarea
          id="weis-chat"
          value={input}
          onChange={(event) => setInput(event.target.value.slice(0, MAX_LENGTH))}
          onKeyDown={handleKeyDown}
          rows={2}
          spellCheck={false}
          placeholder="Ask a follow-up…"
          className="block w-full resize-none bg-transparent px-2.5 py-2 text-[13px] leading-relaxed text-ink outline-none placeholder:text-ink-3"
        />
        <div className="flex items-center justify-end gap-1.5 border-t border-line px-2 py-1.5">
          {isRunning ? (
            <Button size="sm" variant="default" icon={<XIcon size={13} />} onClick={cancel}>
              Cancel
            </Button>
          ) : null}
          <Button
            size="sm"
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
    </Panel>
  )
}
