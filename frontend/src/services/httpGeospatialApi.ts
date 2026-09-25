import type { AgentEvent } from '@/types/agent'
import type {
  GeographicResult,
  KnowledgeReference,
  ResearchPaper,
  TableResult,
} from '@/types/geospatial'
import type { QueryRequest, QueryResponse, SubmitHandle, SubmitOptions } from '@/types/query'

/**
 * HTTP/SSE client for the agent backend.
 *
 * This is the integration seam, and the only transport the app uses:
 *
 *   POST {baseUrl}{queryPath}
 *     body: { query: string, context?: QueryContext }
 *     200  → either
 *              `application/json`   a complete QueryResponse, or
 *              `text/event-stream`  a stream of AgentEvent frames:
 *                                     data: {"type":"tool_call","tool":"buffer",...}
 *
 * Health: GET {baseUrl}{healthPath} → 200 when the service is up.
 *
 * Because the stream is read with `fetch` + a reader rather than `EventSource`,
 * the request can carry a POST body and an auth header, and cancellation works
 * through the same AbortSignal as everything else.
 */
export interface HttpGeospatialApiOptions {
  baseUrl: string
  queryPath?: string
  healthPath?: string
  /** Extra headers, e.g. an authorization token. */
  headers?: Record<string, string>
  fetchImpl?: typeof fetch
}

interface AccumulatedRun {
  results: GeographicResult[]
  explanation?: string
  dataset?: string
  count?: number
  references?: KnowledgeReference[]
  tables?: TableResult[]
  paper?: ResearchPaper
  error?: QueryResponse['error']
  queryId: string
  sawTerminalEvent: boolean
}

export function createHttpGeospatialApi(options: HttpGeospatialApiOptions) {
  const baseUrl = options.baseUrl.replace(/\/$/, '')
  const queryPath = options.queryPath ?? '/query'
  const healthPath = options.healthPath ?? '/health'
  const doFetch = options.fetchImpl ?? fetch

  return {
    kind: 'http' as const,
    endpoint: `${baseUrl}${queryPath}`,

    async checkHealth(signal?: AbortSignal): Promise<'online' | 'offline'> {
      try {
        const response = await doFetch(`${baseUrl}${healthPath}`, {
          method: 'GET',
          signal,
          headers: options.headers,
        })
        return response.ok ? 'online' : 'offline'
      } catch {
        return 'offline'
      }
    },

    submitQuery(request: QueryRequest, submitOptions: SubmitOptions = {}): SubmitHandle {
      const controller = new AbortController()
      const signal = controller.signal
      if (submitOptions.signal) {
        if (submitOptions.signal.aborted) controller.abort()
        else submitOptions.signal.addEventListener('abort', () => controller.abort(), { once: true })
      }

      const startedAt = Date.now()
      let queryId = ''

      const response = (async (): Promise<QueryResponse> => {
        const httpResponse = await doFetch(`${baseUrl}${queryPath}`, {
          method: 'POST',
          signal,
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream, application/json',
            ...options.headers,
          },
          body: JSON.stringify({
            query: request.query,
            context: request.context,
            mode: request.mode ?? submitOptions.mode ?? 'research',
            history: request.history ?? submitOptions.history,
            aims: request.aims ?? submitOptions.aims,
          }),
        })

        if (!httpResponse.ok) {
          const detail = await safeText(httpResponse)
          const error = {
            code: 'query_failed' as const,
            message: `The backend rejected the request (HTTP ${httpResponse.status}).`,
            detail,
            hint: 'Check the backend logs, or the request shape in services/httpGeospatialApi.ts.',
          }
          submitOptions.onEvent?.({ type: 'error', ...error })
          return { queryId, status: 'failed', error, timingMs: Date.now() - startedAt }
        }

        const contentType = httpResponse.headers.get('content-type') ?? ''

        if (!contentType.includes('text/event-stream') || !httpResponse.body) {
          // Non-streaming backend: one complete response, optionally carrying
          // the events it would have streamed.
          const payload = (await httpResponse.json()) as QueryResponse & { events?: AgentEvent[] }
          queryId = payload.queryId ?? queryId
          for (const event of payload.events ?? []) submitOptions.onEvent?.(event)
          return { ...payload, timingMs: payload.timingMs ?? Date.now() - startedAt }
        }

        const run: AccumulatedRun = { results: [], queryId, sawTerminalEvent: false }

        for await (const event of readEventStream(httpResponse.body, signal)) {
          // The streamed query_received frame carries the real run id; without
          // this every SSE run keeps queryId '' and the settled-guard treats
          // all follow-ups as duplicates of the first run.
          if (event.type === 'query_received' && event.queryId) queryId = event.queryId
          submitOptions.onEvent?.(event)
          accumulate(run, event)
        }

        return {
          queryId: run.queryId,
          status: run.error ? 'failed' : 'completed',
          explanation: run.explanation,
          results: run.results,
          dataset: run.dataset,
          count: run.count ?? run.results.reduce((sum, result) => sum + (result.metadata?.count ?? 0), 0),
          references: run.references,
          tables: run.tables,
          paper: run.paper,
          error: run.error,
          timingMs: Date.now() - startedAt,
        }
      })()

      return {
        get queryId() {
          return queryId
        },
        response,
        cancel: () => controller.abort(),
      } as SubmitHandle
    },
  }
}

function accumulate(run: AccumulatedRun, event: AgentEvent): void {
  switch (event.type) {
    case 'query_received':
      run.queryId = event.queryId
      return
    case 'result':
      run.results.push(event.data)
      return
    case 'completed':
      run.sawTerminalEvent = true
      run.explanation = event.explanation ?? run.explanation
      run.dataset = event.dataset ?? run.dataset
      run.count = event.count ?? run.count
      run.references = event.references ?? run.references
      run.tables = event.tables ?? run.tables
      run.paper = event.paper ?? run.paper
      return
    case 'paper':
      run.paper = event.paper
      return
    case 'error':
      run.sawTerminalEvent = true
      run.error = {
        code: event.code,
        message: event.message,
        detail: event.detail,
        hint: event.hint,
      }
      return
    default:
      return
  }
}

/** Parses `text/event-stream` frames into agent events. */
async function* readEventStream(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // Frames are separated by a blank line.
      let separator = buffer.indexOf('\n\n')
      while (separator !== -1) {
        const frame = buffer.slice(0, separator)
        buffer = buffer.slice(separator + 2)
        const event = parseFrame(frame)
        if (event) yield event
        separator = buffer.indexOf('\n\n')
      }
    }
    const tail = parseFrame(buffer)
    if (tail) yield tail
  } finally {
    reader.releaseLock()
  }
}

function parseFrame(frame: string): AgentEvent | null {
  const dataLines = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
  if (dataLines.length === 0) return null
  const payload = dataLines.join('\n')
  if (!payload || payload === '[DONE]') return null
  try {
    const parsed = JSON.parse(payload) as AgentEvent | { event: AgentEvent }
    if (parsed && typeof parsed === 'object' && 'event' in parsed) return parsed.event
    return parsed as AgentEvent
  } catch {
    return null
  }
}

async function safeText(response: Response): Promise<string | undefined> {
  try {
    const text = await response.text()
    return text.slice(0, 500) || undefined
  } catch {
    return undefined
  }
}
