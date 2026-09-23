import { useEffect, useState } from 'react'
import { BACKEND_ENDPOINT, getGeospatialApi } from '@/services/geospatialApi'
import { StatusBadge } from '@/components/ui/Panel'
import type { ConnectionStatus } from '@/types/query'

/**
 * Backend connection indicator.
 *
 * Two states: the agent backend answers, or it does not. The label always
 * says which — colour never carries it alone. Health is re-checked every
 * minute.
 */
export function StatusIndicator() {
  const [status, setStatus] = useState<ConnectionStatus>('checking')

  useEffect(() => {
    let cancelled = false

    async function check() {
      setStatus('checking')
      try {
        const result = await getGeospatialApi().checkHealth()
        if (!cancelled) setStatus(result === 'online' ? 'online' : 'offline')
      } catch {
        if (!cancelled) setStatus('offline')
      }
    }

    void check()
    const timer = window.setInterval(check, 60_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  const description = `Agent backend at ${BACKEND_ENDPOINT}`

  if (status === 'offline') {
    return (
      <StatusBadge tone="critical" dot title={description}>
        Backend offline
      </StatusBadge>
    )
  }

  return (
    <StatusBadge tone={status === 'online' ? 'good' : 'neutral'} dot title={description}>
      {status === 'online' ? 'Backend connected' : 'Checking…'}
    </StatusBadge>
  )
}
