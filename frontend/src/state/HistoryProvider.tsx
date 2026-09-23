import { createContext, useContext, type ReactNode } from 'react'
import { useQueryHistory, type UseQueryHistoryResult } from '@/hooks/useQueryHistory'

/**
 * History lives in its own context so that consumers (the history panel) do not
 * re-render every time a running query emits an agent event, and vice versa.
 */
const HistoryContext = createContext<UseQueryHistoryResult | null>(null)

export function HistoryProvider({ children }: { children: ReactNode }) {
  const history = useQueryHistory()
  return <HistoryContext.Provider value={history}>{children}</HistoryContext.Provider>
}

export function useHistoryState(): UseQueryHistoryResult {
  const value = useContext(HistoryContext)
  if (!value) throw new Error('useHistoryState must be used inside <HistoryProvider>')
  return value
}
