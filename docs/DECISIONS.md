# Decision log

Every significant decision in this project, with context and consequences.
Numbered records (D1…) so code comments, PRs, and paper text can cite them.
Related detail: `docs/RETRIEVAL.md` (indexing, scoring, chunking), `README.md`
(setup, architecture overview).

Status quo reflected here: backend mock-backed for ArcGIS, citation-level
knowledge index, OpenAI planner live, frontend HTTP-only.

---

## A. Agent architecture

### D1 — The LLM plans; deterministic tools execute
The model decides *what to do and which tools fit* and emits an execution
plan. All data fetching, GIS math, and parsing run in typed Python tools.
The model never gets arbitrary Python execution, shell access, or raw SQL,
and never performs spatial arithmetic itself.
Consequence: GIS correctness is testable without an LLM (see D12, tests).

### D2 — Plans are typed DAGs, validated before execution
`agent/plans.py`: `ExecutionPlan` (pydantic) with `id/tool/arguments/depends_on`
steps. `validate_plan` rejects unknown tools, unknown datasets, dangling
dependencies, GIS steps with no input reference, and cycles. The agent
re-validates at its boundary even though the planner already did (defence in
depth). `topo_order` yields dependency levels that are parallel-ready.

### D3 — Intermediate results live in a ResultStore, never in the prompt
Tool outputs are stored under step ids; later tools receive `$step_id`
references resolved by the orchestrator. The LLM sees only `summary_for_llm`
output (counts plus ≤5 sample properties/rows). Rationale: large feature sets
must never enter model context (cost, truncation, leakage of exact records).

### D4 — Planner output via `json_object` + worked example, not `json_schema`
Tried `response_format: json_schema` first. Two live failures against
`gpt-4o-mini`: (1) strict mode rejected the schema (step `arguments` keys vary
per tool, which strict mode forbids → HTTP 400); (2) non-strict mode is
unenforced and the schema vocabulary in the prompt primed the model to *echo
schemas instead of plans*. Fix: plain `json_object` mode, compact tool listing
without schema jargon, a full example plan in the system prompt, and
post-hoc enforcement by `ExecutionPlan` + `validate_plan` (D2).

### D5 — RulePlanner fallback (and test pinning)
Any planner failure (transport error, non-JSON, schema-echo, invalid plan)
falls back to the deterministic `RulePlanner`, which covers the known query
shapes and returns honest `unsupported` otherwise. No key configured → rules
only. Unit tests pin `RulePlanner` so they never depend on model
nondeterminism; the live OpenAI loop is verified via `demos/run_demo.py`.

### D6 — Sequential levels, one transport retry
The orchestrator runs dependency levels in order (steps within a level are
independent by construction and safe to parallelise later). One retry on
transport-flavoured errors (timeout/connection/503/504/rate-limit), else
structural failure records. Events must never break execution (sink guarded).

### D7 — Small tables are inlined for the explanation pass
`table_notes` include actual row values when a table has ≤10 rows, so the LLM
can quote real numbers (e.g. TP mean 0.272 mg-P/L) instead of describing the
table shape. Large tables stay summarised (D3).

### D8 — Citation grounding is mechanical, not model-judged
`agent/grounding.py`: knowledge answers use `[S#]` markers bound to retrieved
hits (globally renumbered, D9b below). The prompt requires a marker per
factual sentence and forbids inventing markers; afterwards invalid markers are
*stripped* and a `citation_check` record (`valid_refs`, `cited`,
`invalid_markers`, `stripped`) is stored in execution metadata. Responses
carry a structured `references` array; the UI renders it as a References
section. Guarantee: no dangling citations. Non-guarantee: a marker may still
misrepresent its passage — entailment checking (human or NLI judge) is future
work.

### D9a — Semantic dataset registry, runtime ArcGIS discovery
The agent reasons about `septic_systems` / `floodplains` /
`maumee_water_quality`, never filenames or URLs. ArcGIS geometry, fields, CRS,
and capabilities come from live `?f=json` discovery — never hardcoded.

### D9b — Global `[S#]` renumbering
Per-call hit labels (`S1…`) are renumbered across all knowledge steps in plan
order, so markers resolve unambiguously even with several retrieval steps.

---

## B. Data sources

### D10 — Mock-backed ArcGIS behind the real interface
The three Lucas County FeatureServers time out from this environment, and
their metadata could not be inspected. Decision: keep the real REST tool
interface (`where`/`bbox`/`out_fields`/pagination) but serve fixtures while
`ARCGIS_USE_MOCK=true`. Fixtures are *provisional by declaration*: assumed
Point/Polygon geometry, minimal attributes (`OBJECTID` + one generic field),
plausible but invented Lucas County coordinates arranged so demos are
meaningful (3 of 10 septic points inside floodplain). Every mock response
carries `mocked: true`, `provisional_schema: true`, the `live_urls` it stands
in for; answers append a mock-data disclaimer and `execution.mocked_datasets`.
Switching to live is one env var, no code change. The model is never told
fixtures are real records.

### D11 — Maumee XLSX as a controlled tabular source
Inspected, not assumed: sheets `ReadMe`/`Maumee_samples`, 22,753 rows,
1975-01-10→2025-09-30, DateTime + 10 parameters × (Qualifier, Value), **no
per-row coordinates** (station time-series). Tool offers
records/summary/daily/schema with row caps; the whole workbook never enters a
prompt. Verified by independent recomputation (test asserts tool summary ==
fresh pandas read). Numbers: TKN 1,605 missing; SO4/SI/COND ~10–11k missing
(later-added parameters). DOI `10.5281/zenodo.6606949` cited.

### D12 — CRS-aware GIS or nothing
`agent/tools/gis/operations.py` (shapely+pyproj): metre-based buffers reproject
to a local metric CRS (UTM for compact extents, azimuthal-equidistant
otherwise) and back — never raw-degree buffering. CRS mismatches
auto-reproject with the transform recorded; invalid geometries go through
`make_valid`, unrepairable ones are dropped and counted. Rationale: a "within
5 km" query answered in degrees is a research-correctness failure.

---

## C. Knowledge / retrieval (see also docs/RETRIEVAL.md)

### D13 — No vector database (evidence-driven)
Both NCWQR pages are year-organised citation lists (titles/authors/venues/DOIs,
no on-page full text). Embeddings would add machinery without a demonstrated
need, so retrieval is a keyword index over verified entries. Full-text PDF
ingestion is the documented next step *only if* citation-level retrieval
proves insufficient.

### D14 — No chunking: whole-entry retrieval
Entries are already atomic (one publication citation + topic line, or one
dataset-fact block), so splitting would only harm precision. Passages truncate
at 1200 chars in hits (800 in prompts). The planned PDF-chunking method is
specified as a proposal in `docs/RETRIEVAL.md`, not implemented.

### D15 — Keyword scoring weights
Tokenise `[A-Za-z0-9]+`, drop generic filler stopwords (kept for ≤4-char
domain codes like TP/NO23), exact word-boundary matches score 2.0 for long
terms / 1.0 for short, sub-word fallback at 0.5× for short codes. Ranked
descending, top-`max_hits` (default 5). Chosen for transparency over
optimality; relevance labels + precision/recall evaluation are future work.

### D16 — Provenance labels inside the index
`ncwqr_index.json` holds: workbook facts (from the file), 2 page-scope
entries (from live fetches), full-page citation ingests (verbatim text, year,
and DOI links from both pages via `scripts/ingest_ncwqr.py`), and 1 entry
explicitly labelled `analyst_synthesis` / "NOT an NCWQR publication". DOIs
spot-verified as resolving at doi.org.

### D17 — Full ingestion replaced relevance selection (superseded)
The index first held 13 hand-selected publications. Challenge: the lab page
alone carries ~180 citations, and hand-selection is selection bias, not a
principle. Resolution: `scripts/ingest_ncwqr.py` parses both live pages (year
headings → citation paragraphs) and ingests every entry verbatim — 179 lab +
133 derived, 317 entries total with the 5 hand entries preserved. Rationale
for the change: recall matters in a knowledge base, and the keyword scorer
handles 317 entries without degradation (verified by test + live queries).
The script is re-runnable, which also makes the index reproducible for paper
methods sections.

---

## D. Configuration and service

### D18 — `OPENAI_KEY` accepted alongside `OPENAI_API_KEY`
The operator's `.env` uses `OPENAI_KEY`; the config reads both (standard name
first). Model via `OPENAI_MODEL` (default `gpt-4o-mini`). Secrets never print
in logs or diagnostics (presence/length only).

### D19 — Flask with hand-rolled CORS, JSON + SSE
No `flask-cors` dependency: an `after_request` hook sets
`Access-Control-Allow-*` and a `query_preflight` route answers OPTIONS. This
was a real bug fix — without it browsers block all reads and the UI reports
"Backend offline" with the server running. Both plain-JSON and SSE
(`text/event-stream`) responses served; SSE is collect-then-stream for exact
ordering. Contract matches `httpGeospatialApi.ts` (`POST /query`, `GET
/health`).

---

## E. Frontend

### D20 — HTTP-only UI; mock deleted
`mockEngine.ts` (779 lines), `mockGeospatialApi.ts`, vendored county data and
its build script removed (~1000+ lines). All answers come from the backend.
Default endpoint `http://localhost:8000`, overridable via `VITE_GEO_API_URL`.

### D21 — Rail tabs: Ask / Progress / History
Initial screen shows only composer + map + results. Progress/History hide
behind tabs; submitting auto-opens Progress exactly once. Running dot on
Progress, entry count on History.

### D22 — Example queries describe the real backend
Six examples covering dataset listing, intersection, buffered intersect, Maumee
summary, publication search, combined GIS+research. Error demos kept only where
valid against the real backend (hospitals, schools, gibberish).

### D23 — OSM default basemap; Ohio initial view
CARTO Positron renders "API key required" watermarks for keyless use → default
is plain OpenStreetMap (keyless). Initial view moved from a mock-era Texas
center to Lucas County, Ohio (41.65, −83.55, z10). Map auto-fits each new
result set (plus manual Fit).

### D24 — Red result pointers
Point markers paint signal-red (`--color-pointer`) for notability; polygons
keep series colours; choropleth and explicit backend styles take precedence.
New `pointer` palette token documents the deliberate exception to the
status-colours rule. Map and legend share `resultColor/resultStroke`, so they
cannot disagree. Reference-city dots stay neutral to avoid confusion with
results.

### D25 — References section in the results dock
`KnowledgeReference[]` flows backend → SSE/JSON → run state → a numbered
References list with DOI links, matching the inline `[S#]` markers (D8).

---

## F. Research readiness

### D26 — Execution metadata is captured for future evaluation
Every response carries `plan`, `selected_tools`, `data_sources`,
`tool_calls` (+ durations), `execution_time_ms`, `errors`, `mocked_datasets`,
`citation_check`. The evaluation harness (benchmark set, ground-truth GIS,
variance runs, ablations) is still to be built — see README §17.

### D27 — Real septic locations are a privacy issue
Fixtures dodge this today, but live parcel-level septic data identifies
private residences. Before any publication or public deployment: aggregate,
jitter, gate access, and write the ethics statement. Flagged early so it is
not discovered late.

## G. Modes (chat / research / spatial / data)

### D28 — One backend, four handling modes
`POST /query` accepts `mode` (`chat` | `research` | `spatial` | `data`,
default `research`) plus `history` (recent `{role, content}` turns).
Research and spatial run the identical full plan→execute pipeline — the
difference is UI emphasis (D30), not capability. Data mode skips the LLM
analysis rewrite and returns deterministic summaries plus raw payloads for
download. Chat mode feeds history into planning (follow-up resolution: "it",
"what about nitrogen?") and into the explanation prompt. Unknown modes fall
back to research; the active mode is recorded in execution metadata.
Rationale: downloading data and chatting are different contracts from
analysis, and conflating them produced vague answers (e.g. analysis prose
over a simple table request).

### D29 — Tables travel with responses; downloads are client-side
The orchestrator forwards tabular tool outputs as `tables` (capped at 200
rows, `row_count` + `truncated` flags preserved) over JSON and SSE. The
frontend renders them with CSV export; feature layers get GeoJSON export.
No download endpoint was added: the bytes already arrived with the answer, so
a server round-trip would be pure overhead. Shown in the results dock in data
mode only, keeping other modes uncluttered.

### D30 — The map is modest except in spatial mode
Heights: chat 140px strip, data 220px, research 300px, spatial flexible
(min 320px, grows). The map auto-fits each new result set in every mode, so
small never means lost. Mode switcher sits atop the rail, always visible;
chat replaces the rail tabs with a thread + pinned composer (turns stored
client-side, history sent per request).

## H. Tabular extremes and parameter recognition
### D31 — "When was X highest" needs dates, full names, and table grounding
A real user query ("when was total suspended solids the highest?") failed
three ways at once: (1) the planner only recognised the code `TSS`, not the
full name; (2) no tool operation returned extreme *dates* — summaries had
min/max values without datetimes; (3) the explanation prompt treated only
knowledge passages as citable, so a combined answer ignored its own table and
claimed the index lacked the information. Fixes: `query_maumee` gained an
`extremes` operation (top-N records with datetimes + the lowest) and
`summaries` now include `min_date`/`max_date`; the rule planner maps ~25 full
parameter names to codes (longest-match-first, word boundaries for short
words) and routes highest/lowest/peak/record/when-was intents to `extremes`;
tool descriptions steer the OpenAI planner to the table path for measured
values; tables became citable `[T#]` sources (orchestrator labels, prompt
includes row values, grounding validates `S` and `T` markers). Verified live:
TSS highest = 2454.1 mg/L on 1990-02-23, cross-checked against an independent
pandas read.

## I. Identity, uploads, and paper output

### D32 — Renamed Geoscope → WEIS
System name is now WEIS (Water Intelligence and Environmental Stewardship)
across UI copy, package metadata, page title, and storage keys (one-time
local reset of history/map prefs accepted). No backend references existed.

### D33 — User uploads become first-class datasets
`POST /api/datasets/upload` (CSV/GeoJSON/XLSX, 25 MB cap) ingests via
`agent/uploads.py` into `data/uploads/` + `registry.json`. CSV/XLSX with
latitude/longitude-like columns materialise to GeoJSON points at ingest so
the query path reads one format; anything else stays tabular. Coordinates are
assumed EPSG:4326, recorded as `crs_assumed` on every entry. `build_registry`
merges uploads as `query_user_dataset` entries (5,000-row ingest cap noted);
the rule planner matches them by registered name and reuses the
buffer/intersect pattern against built-in layers; `list/describe_dataset`
cover them; `DELETE /api/datasets/<name>` is restricted to uploads. Rationale:
asking users to hand over files without making them queryable would strand
their data outside the agent.

### D34 — Research mode writes a paper, aims in, markdown out
`POST /query` accepts `aims` (one per line; research mode). On completion,
`agent/paper.py` assembles title/aims/data/methods/results/limitations/
reproducibility deterministically from the validated plan and execution
record, and generates only abstract/discussion/conclusion via one grounded
LLM call (offline fallback clearly labelled). Markers re-validated; response
carries `paper` + `paper_markdown`; the UI renders a PaperPanel with Markdown
download. Rationale: methods/results must be incapable of hallucination by
construction, while prose stays cited.
