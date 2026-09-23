import { createHttpGeospatialApi } from './httpGeospatialApi'
import type { QueryRequest, QueryResponse, SubmitHandle, SubmitOptions } from '@/types/query'

/**
 * The API boundary.
 *
 * Every component talks to this module and nothing else. All queries go to the
 * agent backend over HTTP/SSE (`httpGeospatialApi.ts`):
 *
 *   POST {baseUrl}/query  body: { query: string, context?: QueryContext }
 *   GET  {baseUrl}/health
 *
 * The backend URL comes from `VITE_GEO_API_URL` and defaults to a local
 * dev server (`http://localhost:8000`, i.e. `python server.py`).
 */

export interface GeospatialApiClient {
  readonly kind: 'http'
  /** The endpoint in use. */
  readonly endpoint: string
  submitQuery(request: QueryRequest, options?: SubmitOptions): SubmitHandle
  checkHealth(signal?: AbortSignal): Promise<'online' | 'offline'>
}

const baseUrl = (import.meta.env.VITE_GEO_API_URL?.trim() || 'http://localhost:8000').replace(
  /\/$/,
  '',
)

export const BACKEND_ENDPOINT = baseUrl

let client: GeospatialApiClient | null = null

export function getGeospatialApi(): GeospatialApiClient {
  if (!client) {
    client = createHttpGeospatialApi({ baseUrl })
  }
  return client
}

/** Convenience wrapper — the call most of the UI makes. */
export function submitGeospatialQuery(
  query: string,
  options?: SubmitOptions,
): SubmitHandle {
  // `context` belongs to the request payload, not to the transport options, so
  // it is lifted onto the body here. A future drawn polygon rides the same path.
  return getGeospatialApi().submitQuery({ query, context: options?.context }, options)
}

export type { QueryRequest, QueryResponse, SubmitHandle, SubmitOptions }
