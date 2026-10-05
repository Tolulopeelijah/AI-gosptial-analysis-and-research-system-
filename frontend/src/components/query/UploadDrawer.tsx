import { useEffect, useRef, useState } from 'react'
import { DataUpload } from './DataUpload'
import { useQueryState } from '@/state/QueryProvider'
import { IconButton } from '@/components/ui/Button'
import { UploadIcon, XIcon } from '@/components/ui/Icons'

/**
 * Dataset uploads behind an icon-rail button.
 *
 * Mirrors `HistoryDrawer`: the trigger lives in the activity rail, and the
 * panel slides over from the left. Composer upload shortcuts open it through
 * `requestUpload()` rather than prop-drilling.
 */
export function UploadDrawer() {
  const [open, setOpen] = useState(false)
  const { uploadRequest } = useQueryState()
  const seenRequest = useRef(uploadRequest)

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  // Composer shortcuts (`requestUpload`) open the drawer wherever it lives.
  useEffect(() => {
    if (uploadRequest !== seenRequest.current) {
      seenRequest.current = uploadRequest
      setOpen(true)
    }
  }, [uploadRequest])

  return (
    <>
      <IconButton
        label="Upload a dataset"
        variant="default"
        active={open}
        onClick={() => setOpen((value) => !value)}
      >
        <UploadIcon />
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
            aria-label="Upload a dataset"
            onClick={(event) => event.stopPropagation()}
            className="absolute bottom-0 left-0 top-0 flex w-full max-w-sm flex-col border-r border-line-strong bg-canvas shadow-[0_12px_40px_rgb(11_11_11/0.20)]"
          >
            <div className="flex shrink-0 items-center justify-between border-b border-line bg-panel px-3 py-2">
              <span className="text-[13px] font-semibold text-ink">Upload a dataset</span>
              <IconButton label="Close upload panel" variant="default" onClick={() => setOpen(false)}>
                <XIcon />
              </IconButton>
            </div>
            <div className="flex min-h-0 flex-1 flex-col p-2">
              <DataUpload />
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
