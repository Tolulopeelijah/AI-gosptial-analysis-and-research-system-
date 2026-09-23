import type { ReactNode } from 'react'
import { HistoryProvider } from './HistoryProvider'
import { QueryProvider } from './QueryProvider'
import { MapProvider } from './MapProvider'

/**
 * Provider composition.
 *
 * Order matters: `QueryProvider` records finished runs into history, so it has
 * to sit inside `HistoryProvider`.
 *
 * Three separate contexts rather than one big store, so a component only
 * re-renders for the slice it actually reads:
 *   HistoryProvider → past queries
 *   QueryProvider   → the current run
 *   MapProvider     → map preferences + commands
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <HistoryProvider>
      <QueryProvider>
        <MapProvider>{children}</MapProvider>
      </QueryProvider>
    </HistoryProvider>
  )
}
