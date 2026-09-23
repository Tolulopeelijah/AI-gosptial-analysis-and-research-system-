import { AppProviders } from '@/state/AppProviders'
import { MainPage } from '@/pages/main/MainPage'
import { ErrorBoundary } from '@/components/layout/ErrorBoundary'

/**
 * Application root.
 *
 * Providers wrap the page rather than the reverse, so the page itself stays a
 * pure layout component and every panel below it can read the state slice it
 * needs without prop-drilling.
 */
export function App() {
  return (
    <ErrorBoundary>
      <AppProviders>
        <MainPage />
      </AppProviders>
    </ErrorBoundary>
  )
}
