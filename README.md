# Geospatial AI Agent Core

Research-oriented **natural-language geospatial agent**: a user asks a geographic
question, the agent understands and decomposes it, selects datasets and tools,
executes GIS operations deterministically, merges intermediate results, and
returns map-ready geographic output — with an optional NCWQR knowledge pathway.

## 1. Purpose

Demonstrate the research pipeline — LLM decides *what to do*, deterministic
tools do the *doing* — over real sources (ArcGIS FeatureServers, NCWQR Maumee
XLSX) while keeping knowledge retrieval (RAG) as a separate, evidence-driven
component. This system is **not** "RAG"; RAG is one optional tool inside it.

## 2. Architecture

```text
User query
  → Agent (agent/agent.py): understand → plan → validate → orchestrate
  → Planner (agent/planner.py): OpenAI structured-output planning (or rule fallback)
  → ExecutionPlan (agent/plans.py): typed, validated DAG of tool steps
  → Orchestrator (agent/orchestration.py): dependency resolution → tool
    execution → ResultStore ($step_id refs) → retries → aggregation
  → Tools (agent/tools/): data access | GIS processing | knowledge | utility
  → FinalResult: GeoJSON layers + tables + explanation + sources + execution metadata
  → Frontend / map (POST /query, GET /health in server.py)
```

Core principle: **the LLM never performs spatial math.** Buffer, intersect,
nearest, and all data fetching run in deterministic Python (shapely/pyproj,
requests, pandas).

## 3. Repository structure

```text
agent/                  # backend core
  agent.py              # GeospatialAgent.ask(): the agent loop
  planner.py            # OpenAIPlanner + RulePlanner → ExecutionPlan
  plans.py              # typed plan schema + validation + topo ordering
  orchestration.py      # dependency execution, retries, result merging
  registry.py           # semantic dataset registry (no invented schemas)
  results.py            # ResultStore ($refs) + GeoJSON/final-response builders
  config.py             # env-based settings (OPENAI_*, ARCGIS_*_URL, ...)
  tools/
    __init__.py         # Tool dataclass + ToolRegistry (+ OpenAI definitions)
    registry.py         # wires the 8 tools
    data/arcgis.py      # query_arcgis (semantic dataset → REST, runtime metadata)
    data/xlsx.py        # query_maumee (records/summary/daily/schema)
    gis/operations.py   # buffer / intersect / nearest (CRS-aware)
    knowledge/retrieval.py  # search_knowledge_base (curated index; RAG seam)
    utility/schema.py   # list_datasets / describe_dataset
server.py               # Flask API: POST /query (JSON or SSE), GET /health
knowledge/ncwqr_index.json  # curated, provenance-labelled knowledge index
data/HTLP_Export_*.xlsx     # NCWQR Maumee time-series (inspected, see §4)
tests/test_agent_core.py    # 27 tests (plans, GIS, tools, mocks, orchestration, e2e)
demos/run_demo.py           # the 5 spec demo queries + Maumee summary
frontend/               # pre-existing React/Leaflet UI (mock or VITE_GEO_API_URL)
```

## 4. Data sources

| Semantic name | Type | Content (inspected) |
|---|---|---|
| `septic_systems` | ArcGIS FeatureServer (**mock-backed**) | LCHD layer 0; live metadata unfetchable (server timeouts), so fixtures serve: Point geometry (assumed), `OBJECTID` + `STATUS` (provisional). Real URL kept in config; `ARCGIS_USE_MOCK=false` switches to live with no code change |
| `floodplains` | ArcGIS FeatureServer ×2 (**mock-backed**) | Layers 0 + 4; fixtures: Polygons (assumed), `OBJECTID` + `ZONE` (provisional). Same live-switch mechanism |
| `maumee_water_quality` | Local XLSX (real) | Sheets `ReadMe`, `Maumee_samples`; 22,753 rows 1975-01-10→2025-09-30; DateTime + 10 params × (Qualifier, Value): FLOW, TSS, TP, SRP, NO23, TKN, CL, SO4, SI, COND. **Station time-series: no per-row coordinates.** Missing values: TKN 1,605; SO4/SI/COND ~10–11k (later-added params). Citation DOI `10.5281/zenodo.6606949`. |

Mock honesty: every mock response carries `mocked: true`, `provisional_schema:
true`, the `live_urls` it stands in for, and a note; final answers append a
mock-data disclaimer naming the affected datasets, and `execution` records
`mocked_datasets`. The model is never told fixtures are real records.

## 5. Knowledge sources

Two NCWQR publication pages (Lab Publications, Derived Works) are the intended
knowledge base; their URLs are pending (`NCWQR_PUBLICATIONS_URL`,
`NCWQR_DERIVED_WORKS_URL`).

## 6. RAG architecture — evidence-driven decision

**No vector DB/embeddings were built, deliberately.** Both NCWQR pages were
fetched and verified accessible, and their content is a year-organized
citation list (titles, authors, venues, DOIs) — no full text on-page. The
proportionate retrieval architecture is therefore citation-level, not
embedding-level:

```text
live NCWQR pages → page-scope + selected relevant publication entries
(with DOIs) → knowledge/ncwqr_index.json → search_knowledge_base(query)
→ ranked passages + {source, title, identifier, url} → LLM explanation
```

The index holds dataset metadata plus the full citation lists of both pages
(179 lab + 133 derived entries, ingested verbatim by the re-runnable
`scripts/ingest_ncwqr.py`, with titles/authors/DOIs exactly as published).
Topic summaries are paraphrased strictly from titles — no findings asserted
beyond the citation.
`retrieval.py::_load_index` remains the seam for chunk ingestion; full-text
PDF retrieval would be the next step only if citation-level proves
insufficient.

## 7. Tool architecture

Each tool: unique name, description, JSON input schema, deterministic function,
structured dict output (`ok` + payload or `ok: False` + `error`). No arbitrary
Python/SQL/shell is exposed. `ToolRegistry.openai_definitions()` renders OpenAI
function-calling schemas.

| Tool | Category | Input → output |
|---|---|---|
| `query_arcgis` | data | semantic `dataset` + where/bbox → GeoJSON FeatureCollection |
| `query_maumee` | data | param/date-range/operation → table |
| `buffer` | gis | `$ref` + distance/unit → FeatureCollection |
| `intersect` | gis | `$ref` A × `$ref` B → matching A features |
| `nearest` | gis | `$ref` A × `$ref` B + k → distance table (km) |
| `search_knowledge_base` | knowledge | query → passages + provenance |
| `list_datasets` / `describe_dataset` | utility | registry / live layer metadata |

## 8. How tools are exposed to OpenAI

`build_tool_registry().openai_definitions()` → `tools=[...]` on
`chat.completions.create` with `tool_choice="none"` (planner mode: the model
sees real schemas so it plans with real tools, but emits the plan as JSON
rather than calling). Planning uses `response_format={"type": "json_object"}`
plus a worked example — deliberately NOT `json_schema`, after live testing
showed non-strict schemas are unenforced and schema vocabulary primes the
model to echo schemas instead of plans. Structure is enforced afterwards by
the typed `ExecutionPlan` + `validate_plan`, with `RulePlanner` fallback on
any failure. Model/key from `OPENAI_MODEL` / `OPENAI_API_KEY` (or `OPENAI_KEY`).
Live-verified with `gpt-4o-mini`: model → plan → mock tools → execution →
grounded interpretation with DOI citations.

## 9. Execution-plan structure

```json
{"goal": "...", "steps": [{"id": "floodplains", "tool": "query_arcgis",
 "arguments": {"dataset": "floodplains"}, "depends_on": []},
 {"id": "buffer", "tool": "buffer",
  "arguments": {"input": "$floodplains", "distance": 2000, "unit": "meters"},
  "depends_on": ["floodplains"]}]}
```

`validate_plan` rejects unknown tools/datasets, dangling deps, GIS steps with
no input refs, and cycles. `topo_order` yields dependency levels (parallel-ready).

## 10. Orchestration

Level-by-level execution; `$step_id` refs resolved from the `ResultStore`
before each call; one retry on transport-flavoured errors; per-call timing;
failures recorded structurally; aggregation merges GeoJSON layers (last
FeatureCollection step = primary), table notes, knowledge sources, and full
execution metadata (`plan`, `selected_tools`, `data_sources`, `tool_calls`,
`execution_time_ms`, `errors`).

## 11. Intermediate-result handling

Tool outputs live in `ResultStore` keyed by step id; later tools receive
`$id` references, never raw payloads. The LLM sees only small summaries
(`summary_for_llm`: counts + ≤5 sample properties/rows) — large feature sets
never enter model context.

## 12. Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill OPENAI_API_KEY, ARCGIS_*_URL, NCWQR_*_URL
python demos/run_demo.py
python -m pytest tests/ -q
python server.py        # → http://localhost:8000 (/health, /query)
```

Frontend: `cd frontend && npm install && VITE_GEO_API_URL=http://localhost:8000 npm run dev`.

## 13. Environment variables

See `.env.example`. `OPENAI_API_KEY` (planner/explainer; unset → rule planner),
`OPENAI_MODEL` (default `gpt-4o-mini`), `ARCGIS_SEPTIC_URL`,
`ARCGIS_FLOODPLAIN_0_URL`, `ARCGIS_FLOODPLAIN_4_URL`,
`NCWQR_PUBLICATIONS_URL`, `NCWQR_DERIVED_WORKS_URL`, `MAUMEE_XLSX_PATH`
(auto-discovers `data/*.xlsx`), `KNOWLEDGE_INDEX_PATH`. `.env` is gitignored.

## 14. Example queries
1. `Show septic systems in the available dataset.` (mock-backed until live ArcGIS is reachable)
2. `Find septic systems that intersect floodplain areas.`
3. `Find septic systems within 2 km of floodplain areas.` (buffer 2000 m + intersect)
4. `Find the relevant NCWQR publications about water-quality implications…` (knowledge)
5. Combined GIS + knowledge (see demos/run_demo.py) + `Summarize total phosphorus (TP) in the Maumee dataset.` (works today, no key needed)

## 15. How to run the agent

```python
from agent.agent import GeospatialAgent
resp = GeospatialAgent().ask("Summarize TP in the Maumee dataset", mode="data")
# resp: {queryId, status, explanation, results?, tables?, dataset?, count?,
#        sources?, references?, execution?, timingMs?}
```

## Modes

`POST /query` accepts `mode` (`chat` | `research` | `spatial` | `data`,
default `research`) and, for chat, `history` (recent `{role, content}` turns):

| Mode | Backend | UI |
|---|---|---|
| `chat` | Pipeline + history-aware planning/explanation, follow-ups resolve | Thread + composer; map is a 140px strip |
| `research` | Full plan → execute → explain + references (current behavior) | Composer + full dock; compact 300px map |
| `spatial` | Same pipeline as research | Map takes the room (min 320px, grows) |
| `data` | Pipeline, but no LLM analysis rewrite; raw `tables` (+ layers) for download | Compact map; Data panel with CSV/GeoJSON export |

Tables are capped at 200 rows per response (`row_count` + `truncated` tell the
full story); downloads are generated client-side from bytes already received.
See `docs/DECISIONS.md` (D28–D30).

## 16. Current limitations

- ArcGIS tools are mock-backed (`ARCGIS_USE_MOCK=true`) because the live
  servers time out from here; fixture geometry/attributes are provisional and
  every answer says so. Flip one env var when reachable.
- Knowledge index is citation-level (full citation lists: 179 lab + 133 derived) —
  no full-text PDFs yet.
- `RulePlanner` covers demo shapes when no key is set; the OpenAI planner is
  live-verified but small models need the JSON-object + example prompting
  (documented in §8) — re-validate prompts if the model changes.
- Orchestrator runs dependency levels sequentially (parallel-ready structure).
- Maumee data is station-level tabular — it cannot answer per-feature spatial
  questions; cross-linking it to GIS geometries is out of scope.

## 17. Future extensions

Provide ArcGIS + NCWQR URLs → verify live metadata → ingest publication
full texts (upgrade `ncwqr_index.json` via the `retrieval.py` seam, add
embeddings only if keyword retrieval proves insufficient) → live OpenAI
planner evaluation (validity, tool selection, latency) → parallel level
execution → PostGIS/GeoJSON/CSV tools → drawn-polygon `QueryContext` support.

## Glossary- **Agent** (`agent.py`): owns the loop; calls planner, validates, orchestrates.
- **Planner** (`planner.py`): LLM (or rules) turning language into an ExecutionPlan.
- **Orchestrator** (`orchestration.py`): executes validated plans via tools.
- **Tool**: deterministic function with a model-visible schema.
- **Data source**: ArcGIS layers / XLSX (structured access, not RAG).
- **GIS operation**: deterministic spatial computation (buffer/intersect/nearest).
- **Knowledge source**: NCWQR pages; **RAG** = the optional passage-retrieval tool.
- **Result**: merged GeoJSON + tables + explanation + citations + metadata.

## Documentation

- `docs/DECISIONS.md` — every project decision (D1–D27) with context and
  consequences: architecture, mocks, retrieval, prompts, CORS, UI, and the
  privacy flag on real septic locations.
- `docs/RETRIEVAL.md` — indexing/scoring/chunking policy: currently
  whole-entry retrieval with weighted keyword scoring and no chunking; the
  proposed PDF-chunking method is specified there for review before it is
  ever built.
