import { useEffect, useState } from 'react'
import { HistoryPanel } from './HistoryPanel'
import { useQueryState } from '@/state/QueryProvider'
import { Button, IconButton } from '@/components/ui/Button'
import { MenuIcon, PlusIcon, XIcon } from '@/components/ui/Icons'

/**
 * Past prompts behind a hamburger menu.
 *
 * The trigger sits at the far left of the header; the drawer slides over from
 * the left with a New Chat button on top and the full history list below it.
 * Selecting an entry restores it and closes the drawer.
 */
export function HistoryDrawer() {
  const [open, setOpen] = useState(false)
  const { setMode, clearChat, query, setDraft } = useQueryState()

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open ])

  function startNewChat() {
    setMode('chat')
    clearChat()
    query.reset()
    setDraft('')
    setOpen(false)
  }

  return (
    <>
      <IconButton
        label="Past prompts"
        variant="default"
        active={open}
        onClick={() => setOpen((value) => !value)}
      >
        <MenuIcon />
      </IconButton>

      {open ? (
        <div
          className="fixed inset-0 z-[2000]"
          role="presentation"
          onClick={() => setOpen(false)}
        >
          <div className="absolute inset-0 bg-ink/25" aria-hidden="true" />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Past prompts"
            onClick={(event) => event.stopPropagation()}
            className="absolute bottom-0 left-0 top-0 flex w-full max-w-sm flex-col border-r border-line-strong bg-canvas shadow-[0_12px_40px_rgb(11_11_11/0.20)]"
          >
            <div className="flex shrink-0 items-center justify-between border-b border-line bg-panel px-3 py-2">
              <span className="text-[13px] font-semibold text-ink">Past prompts</span>
              <IconButton label="Close past prompts" variant="default" onClick={() => setOpen(false)}>
                <XIcon />
              </IconButton>
            </div>
            <div className="shrink-0 border-b border-line bg-panel p-2">
              <Button
                size="sm"
                variant="primary"
                fullWidth
                icon={<PlusIcon size={13} />}
                onClick={startNewChat}
              >
                New chat
              </Button>
            </div>
            <div className="flex min-h-0 flex-1 flex-col p-2">
              <HistoryPanel onSelect={() => setOpen(false)} />
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
