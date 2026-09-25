# WEIS

A research-oriented frontend for a geospatial AI system. You ask a question in
natural language; an agent resolves it into datasets and GIS operations and the
result is drawn and tabulated.

This repository is the **interface layer** of the architecture in
`proposed_architecture.png` — the natural-language query surface and the map
visualization layer. The agent, the data layer, the GIS tooling and the
orchestration layer are **not implemented here**. Everything the interface needs
from them arrives through one narrow module, `src/services/geospatialApi.ts`,
which currently answers from an in-browser mock service.

```
┌─ Interface layer (this repo) ───────────────────────────────┐
│  Query composer → agent event stream → map + results dock   │
└──────────────────────────┬──────────────────────────────────┘
                           │  submitGeospatialQuery()
                           │  AgentEvent stream
┌──────────────────────────┴──────────────────────────────────┐
│  Orchestration / agent / GIS tools / data  (to be built)    │
└─────────────────────────────────────────────────────────────┘
```

---

## Running it

```bash
npm install
node scripts/build-county-data.mjs   # writes public/data/counties.geo.json
npm run dev                          # http://localhost:5173
```

Other scripts:

```bash
npm run typecheck   # tsc --noEmit
npm run build       # typecheck, then a production build into dist/
npm run preview     # serve the production build
```

### The dataset

The demo runs against six states — Texas, California, Oklahoma, New Mexico,
Louisiana and Arkansas — 561 counties of US county boundaries with 2020 census
population. It is **not committed**; `scripts/build-county-data.mjs` fetches it
from two public-domain sources (Census cartographic boundaries, Census
population estimates), simplifies the geometry with Douglas–Peucker at ~2 km,
rounds coordinates to 3 decimals and writes about 220 KiB of GeoJSON to
`public/data/counties.geo.json`.

Without that step the map still loads and every query fails with
`data_unavailable` — which is a real code path, and the error names the script
to run.

To widen the demo, edit `STATE_FIPS` in the script and re-run it. The query
engine picks up whatever states are present, including which states it can
report as loaded when a query asks for one that is missing.

---

## What it does

Ask in the composer. Press `Enter` to run, `Shift+Enter` for a new line. The
left rail shows the agent's plan and tool calls as they stream; the map draws
each result layer as it arrives; the bottom dock reports the figures, the
agent's explanation and the attribute table.

Eight example queries are in the composer, two in each of four tiers, grouped by
the reasoning each one demands. One per tier:

| Tier | Example | What it exercises |
|---|---|---|
| Region | `Show counties in Texas` | Place name → boundary → feature selection |
| Attribute filter | `Show counties with population above 100,000` | Numeric threshold across the dataset |
| Spatial filter | `Find counties within 50 km of Dallas` | Buffer construction and a distance test |
| Multi-step | `Show counties with population above 100,000 that are within 50 km of Dallas` | Decomposition, then recombination |

The parser handles population thresholds (`100k`, `1.5 million`, `above`,
`below`, `>`), distances in km/miles, state names and FIPS codes, and named
cities. Anything it cannot resolve produces a specific, explained failure rather
than a generic one.

### Failure paths

These are worth trying, and are listed in the app's help dialog. Each is a
distinct case in the UI:

| Query | Outcome |
|---|---|
| `Show hospitals in this area` | `data_unavailable` — no hospital dataset is registered |
| `Show counties in Florida` | `data_unavailable` — names the states that *are* loaded |
| `Show counties with population above 50,000,000` | Completed with **0 features** — a valid query with no match is a result, not an error |
| `asdfgh qwerty` | `invalid_geographic_query` — nothing identifiable in the text |
| `simulate processing error` | `processing_error` — a tool call fails mid-plan, and the steps that completed are preserved |

A sixth path — `backend_unavailable` — is reached from **Settings → Service →
Simulate offline backend**, which makes the next submission fail the way an
unreachable service would.

---

## Colour system

The map carries the only saturated colour in the interface. The palette is
fixed and small, and each part of it has one job:

| Job | Tokens | Rule |
|---|---|---|
| **Identity** — which layer is which | `series-1..3` (blue, orange, green) | Assigned in fixed order and never cycled. A fourth layer gets the neutral `other` treatment, not a generated hue. |
| **Magnitude** — the choropleth | `seq-100..700`, one hue, light → dark | Five quantile classes by default. Quantile rather than equal-interval because county population is heavily skewed — equal-count classes keep each legend swatch meaningful. |
| **State** — success, warning, failure | `good`, `warning`, `critical` | Reserved. Never reused as a series colour, and always accompanied by a label or an icon so colour is never the only carrier. |

Consequences that are enforced in code rather than left to discipline:

- **The legend is always present** when something is drawn (`MapLegend`), and a
  graduated layer lists its real class ranges, not a gradient. The legend and
  the map read from the same module (`lib/resultStyle.ts`) so they cannot
  disagree about a colour.
- **Text never wears a data colour.** Values, labels and headings use ink
  tokens; a coloured swatch beside them carries the identity.
- **Status is carried by shape as well as colour** — completed steps show a
  tick, failed ones a warning triangle, pending ones a hollow dot
  (`ProcessingPanel`).
- **Light surfaces only.** The palette is specified and validated against a
  light chart surface, so all four basemaps are light styles. A dark basemap
  would need its own ramp steps, so none is offered.

The tokens exist twice on purpose: as CSS custom properties in `src/index.css`
for anything React styles, and as constants in `src/lib/palette.ts` for anything
handed to Leaflet — Leaflet sets SVG presentation attributes imperatively, where
a `var(--token)` string would not resolve. The reason is documented in the file.

---

## Architecture

```
src/
├── types/            Contracts only — no runtime code
│   ├── agent.ts        AgentEvent union, error codes, ProcessingStep
│   ├── geospatial.ts   GeographicResult, ChoroplethSpec, QueryContext
│   ├── query.ts        QueryRequest/Response, QueryRun, history entries
│   └── map.ts          Basemaps, layer visibility, legend model
│
├── services/         The API boundary — the only place transport is decided
│   ├── geospatialApi.ts     Facade: picks mock or HTTP once, at import
│   ├── mockGeospatialApi.ts Mock transport: replays a plan as timed events
│   ├── mockEngine.ts        The fake GIS backend (query parsing + geometry)
│   ├── httpGeospatialApi.ts HTTP/SSE client — the real integration seam
│   └── agentSteps.ts        AgentEvent[] → ProcessingStep[] (pure)
│
├── state/            Three contexts, composed in AppProviders
│   ├── HistoryProvider.tsx  Past queries
│   ├── QueryProvider.tsx    The current run + the composer draft
│   └── MapProvider.tsx      Map preferences + the imperative command channel
│
├── hooks/            useGeospatialQuery, useQueryHistory, useDismissable,
│                     mapController (the interface the map registers)
│
├── components/
│   ├── layout/       Header, status indicator, settings, help, error boundary
│   ├── query/        Composer and clickable examples
│   ├── processing/   The agent's step list
│   ├── results/      Stat tiles, attribute table, distribution, layers, errors
│   ├── history/      Past queries
│   ├── map/          MapCanvas + layers, controls, legend, status bar
│   └── ui/           Panel, Button, StatTile, Icons — the whole design system
│
├── data/             Static content: app copy, basemaps, examples, places
├── lib/              Pure helpers: geometry, formatting, palette, legend
└── pages/main/       MainPage — the workbench layout
```

### State, separated by concern

Three contexts rather than one store, so a component re-renders only for the
slice it reads:

- **`HistoryProvider`** — finished queries. A history row does not re-render
  when a running query emits an event.
- **`QueryProvider`** — the current run (`QueryRun`: status, steps, results,
  explanation, error) plus the composer draft.
- **`MapProvider`** — map preferences (persisted to localStorage) and the
  command channel.

The reducer in `hooks/useGeospatialQuery.ts` is the only place a run changes
state, and it consumes `AgentEvent`s — not query text. Nothing in the UI layer
knows what a "buffer" is.

---

## How mock responses work

`src/services/geospatialApi.ts` reads `VITE_GEO_API_URL` once at import:

```
VITE_GEO_API_URL set   → createHttpGeospatialApi()   (POST /query, SSE or JSON)
VITE_GEO_API_URL unset → createMockGeospatialApi()   (in-browser, no network)
```

Which branch is live is shown in the header, next to the status indicator — a
mock response is never presented as a real one.

### The event contract

The mock emits exactly what a streaming backend is expected to emit, so the UI
cannot tell the difference:

```ts
type AgentEvent =
  | { type: 'query_received'; queryId: string }
  | { type: 'planning'; message: string; tasks?: string[]
      plan?: Array<{ id: string; tool: string; label: string }> }
  | { type: 'tool_call'; tool: string; status: 'started' | 'completed' | 'failed'
      message?: string; detail?: string; durationMs?: number }
  | { type: 'result'; data: GeographicResult }
  | { type: 'completed'; explanation?: string; dataset?: string; count?: number }
  | { type: 'error'; code: GeoErrorCode; message: string; detail?: string; hint?: string }
```

`planning.plan` is what lets the processing panel show the *whole* task list up
front with later steps pending, rather than only revealing work after it
happens. A backend that omits it still works — steps are appended as tool calls
arrive instead.

`services/agentSteps.ts` folds these events into the `ProcessingStep[]` the
panel renders. It is pure and has no React dependency, so it is directly
testable. The panel has never seen an `AgentEvent`.

### The response contract

`submitGeospatialQuery(query, options)` returns a `SubmitHandle`:
`{ queryId, response: Promise<QueryResponse>, cancel() }`. `QueryResponse`
carries `status`, `results: GeographicResult[]`, `explanation`, `dataset`,
`count`, `error` and `timingMs`. Streaming backends deliver results through
`result` events; single-response backends deliver them in the resolved object.
Both paths are handled.

### Connecting the real backend

1. Run it, speaking the contract documented at the top of
   `src/services/httpGeospatialApi.ts`:

   ```
   POST {base}/query   { query: string, context?: QueryContext }
     200 application/json      → a complete QueryResponse, optionally with `events: AgentEvent[]`
     200 text/event-stream     → `data: {"type":"tool_call",...}` frames
   GET  {base}/health          → 200 when the service is up
   ```

2. Point the frontend at it:

   ```bash
   echo 'VITE_GEO_API_URL=http://localhost:8000' > .env.local
   ```

3. Restart the dev server. No component changes. The status indicator switches
   from "Mock service" to "Backend connected" / "Backend offline", and the
   offline simulation switch disappears (it is mock-only).

The SSE reader uses `fetch` + a stream reader rather than `EventSource`, because
`EventSource` cannot send a POST body or an auth header. Cancellation runs
through the same `AbortSignal` as everything else.

---

## Map input architecture

**The map is an output surface.** Queries are asked in natural language; nothing
requires drawing on the map. But the seams for map input exist, and none of them
require restructuring:

- **`QueryContext`** (`src/types/geospatial.ts`) already carries `mapBounds`,
  `mapCenter`, `mapZoom`, `selection` (any GeoJSON) and `selectionLabel`. The
  composer attaches the current view to every request today; a drawn polygon
  would fill `selection` and travel the identical path to the backend.
- **`MapController`** (`src/hooks/mapController.ts`) is the imperative interface
  the map registers into context. A new map interaction — draw a polygon, select
  a county — is another method on this interface; no other component imports
  Leaflet.
- **Map clicks already work**: clicking the map produces a coordinate read-out
  in the status bar with a copyable lat/lng. Sending those coordinates as
  `selection` is the next step and needs no new plumbing.
- **Leaflet is driven imperatively** rather than through `react-leaflet`. The
  result layers are large GeoJSON collections that should be diffed by identity,
  not re-rendered by React, and it keeps the dependency list to React, Leaflet
  and Tailwind.

---

## Notes on a few decisions

**History is localStorage, and metadata only.** A single county result can be
several megabytes and localStorage caps out around 5 MB per origin, so the
GeoJSON is never persisted. Within a session, clicking a history row restores
its layers from a capped in-memory cache keyed by run id. After a reload the
geometry is gone, and the row says so and loads the query text for a re-run
instead of pretending it still has the data.

**The dataset is fetched, not imported.** A multi-megabyte JSON in `src/` would
enter the JS bundle and make TypeScript infer an enormous literal type. It lives
in `public/data/` and is fetched at runtime by `src/data/counties.ts`.

**"No results" is a completed run, not a failure.** A GIS tool that reports zero
matching features as an error is lying about what happened. The dock renders it
as a distinct outcome — the query was valid and executed, nothing satisfied it —
with the threshold it applied.

**Errors are enumerated, never generic.** `GeoErrorCode` has eight members and
`components/results/ErrorNotice.tsx` gives each one its own heading, body and
suggested next step, because "the service is down" and "that dataset isn't
loaded" call for different actions. There is deliberately no fallback string
like "Something went wrong": an unrecognised code shows the code itself.

---

## Stack

React 19 · TypeScript (strict) · Vite 6 · Tailwind CSS v4 · Leaflet 1.9

Three runtime dependencies — `react`, `react-dom` and `leaflet` — and no
component library: the design system is five files in `src/components/ui/`.
Map tiles © OpenStreetMap contributors, © CARTO; county data from the US Census
Bureau (public domain).
