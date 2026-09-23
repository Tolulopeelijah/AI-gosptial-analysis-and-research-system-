import { useCallback, useEffect, useRef } from 'react'
import type { RefObject } from 'react'

/**
 * Closes a floating element on outside click, Escape, or focus loss.
 * Returns the ref to attach to the floating element.
 */
export function useDismissable<T extends HTMLElement>(
  isOpen: boolean,
  onDismiss: () => void,
  options: { ignore?: RefObject<HTMLElement | null> } = {},
) {
  const ref = useRef<T | null>(null)
  const onDismissRef = useRef(onDismiss)
  onDismissRef.current = onDismiss

  const handlePointerDown = useCallback(
    (event: PointerEvent) => {
      const target = event.target as Node | null
      if (!target) return
      if (ref.current?.contains(target)) return
      if (options.ignore?.current?.contains(target)) return
      onDismissRef.current()
    },
    [options.ignore],
  )

  useEffect(() => {
    if (!isOpen) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onDismissRef.current()
      }
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [isOpen, handlePointerDown])

  return ref
}
