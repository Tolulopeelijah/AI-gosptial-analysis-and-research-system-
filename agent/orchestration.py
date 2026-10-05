"""Orchestrated execution of validated plans.

Responsibilities: dependency resolution (level by level; levels are
parallel-capable), `$step_id` reference resolution against the ResultStore,
tool dispatch, one retry on transport-flavoured failures, output validation,
intermediate-result storage, and final aggregation into GIS layers + tables +
knowledge sources + execution metadata.
"""

from __future__ import annotations

import logging
import json
import time
from typing import Any, Callable, Dict, List, Optional

from .plans import ExecutionPlan, topo_order
from .results import ResultStore, build_final_response, feature_collection

log = logging.getLogger(__name__)

# Max table rows forwarded in a response (downloads stay usable offline).
MAX_TABLE_ROWS = 200

EventSink = Optional[Callable[[Dict[str, Any]], None]]

_RETRYABLE = ("timeout", "timed out", "connection", "503", "504", "rate limit")


def _resolve_refs(arguments: Dict[str, Any], store: ResultStore) -> Dict[str, Any]:
    def resolve(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("$"):
            return store.get(value)
        if isinstance(value, list):
            return [resolve(v) for v in value]
        return value

    return {key: resolve(value) for key, value in arguments.items()}


def _is_retryable(error: str) -> bool:
    low = error.lower()
    return any(t in low for t in _RETRYABLE)


class Orchestrator:
    def __init__(self, tool_registry, max_retries: int = 1):
        self.tools = tool_registry
        self.max_retries = max_retries

    def execute(
        self,
        plan: ExecutionPlan,
        *,
        query_id: str,
        on_event: EventSink = None,
    ) -> Dict[str, Any]:
        t0 = time.time()
        store = ResultStore()
        tool_calls: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        levels = topo_order(plan)

        def emit(event: Dict[str, Any]) -> None:
            if on_event:
                try:
                    on_event(event)
                except Exception:  # events must never break execution
                    log.exception("event sink failed")

        for level in levels:
            # Levels run sequentially here; steps *within* a level are
            # independent by construction and safe to parallelise later.
            for step in level:
                emit({"type": "tool_call", "tool": step.tool, "status": "started",
                      "detail": step.id})
                started = time.time()
                try:
                    args = _resolve_refs(dict(step.arguments), store)
                except KeyError as exc:
                    err = f"unresolved reference: {exc}"
                    errors.append({"step": step.id, "error": err})
                    emit({"type": "tool_call", "tool": step.tool,
                          "status": "failed", "message": err})
                    continue
                output = self.tools.run(step.tool, args)
                if not output.get("ok") and _is_retryable(str(output.get("error", ""))) \
                        and self.max_retries > 0:
                    time.sleep(1.0)
                    output = self.tools.run(step.tool, args)
                duration = int((time.time() - started) * 1000)
                tool_calls.append({"step": step.id, "tool": step.tool,
                                   "ok": bool(output.get("ok")),
                                   "duration_ms": duration})
                if output.get("ok"):
                    store.put(step.id, output)
                    emit({"type": "tool_call", "tool": step.tool,
                          "status": "completed",
                          "message": self._summarize(step.tool, output),
                          "durationMs": duration})
                else:
                    errors.append({"step": step.id, "tool": step.tool,
                                   "error": output.get("error")})
                    emit({"type": "tool_call", "tool": step.tool,
                          "status": "failed", "message": output.get("error"),
                          "durationMs": duration})

        return self._aggregate(
            plan, store, tool_calls, errors, query_id,
            execution_ms=int((time.time() - t0) * 1000),
        )

    # ------------------------------------------------------------- helpers ---

    @staticmethod
    def _summarize(tool: str, output: Dict[str, Any]) -> str:
        if output.get("type") == "FeatureCollection":
            note = (f" ({output['count']} of {output['total_count']})"
                    if output.get("truncated") and output.get("total_count")
                    else "")
            truncated = " (truncated)" if output.get("truncated") and not note else ""
            return f"{output.get('count', 0)} features loaded{note}{truncated}"
        if output.get("type") == "table":
            return f"{output.get('row_count', 0)} rows"
        if output.get("type") == "knowledge":
            return f"{output.get('count', 0)} passages retrieved"
        return "done"

    def _aggregate(self, plan, store, tool_calls, errors, query_id,
                   execution_ms: int) -> Dict[str, Any]:
        layers: List[Dict[str, Any]] = []
        sources: List[Dict[str, Any]] = []
        references: List[Dict[str, Any]] = []
        tables: List[Dict[str, Any]] = []
        downloads: List[Dict[str, Any]] = []
        datasets: List[str] = []
        operations: List[str] = []
        table_notes: List[str] = []
        mocked: List[str] = []
        truncation_warnings: List[str] = []
        ref_counter = 0
        fatal = [e for e in errors]

        for step in plan.steps:
            if not store.has(step.id):
                continue
            out = store.get(step.id)
            operations.append(step.tool)
            if isinstance(out, dict) and out.get("mocked"):
                mocked.append(out.get("dataset", step.id))
            if isinstance(out, dict) and out.get("type") == "FeatureCollection":
                is_final = step.id in ("result",) or step.id == plan.steps[-1].id
                warning = out.get("truncation_warning")
                if warning and warning not in truncation_warnings:
                    truncation_warnings.append(warning)
                sample_note = ""
                if out.get("truncated"):
                    total = out.get("total_count")
                    sample_note = (
                        f"sampled first {out.get('count', 0)} of {total}"
                        if total else
                        f"sampled first {out.get('count', 0)} (server cap)"
                    )
                for le in (out.get("layer_errors") or [])[:1]:
                    err_short = le if len(le) <= 180 else le[:180] + "…"
                    sample_note += (("; " if sample_note else "")
                                    + f"layer trouble: {err_short}")
                puc = out.get("per_url_counts") or []
                if len(puc) > 1 or any(
                        (e.get("total") or 0) > 0 and not e.get("fetched")
                        for e in puc):
                    # Multi-URL honesty: show which service layer contributed
                    # what (e.g. "MapServer/6: 0/3369; MapServer/7: 14/14"),
                    # so silent per-layer gaps are visible without digging.
                    bits = []
                    for e in puc:
                        tail = "/".join(
                            str(e.get("url") or "").rstrip("/").split("/")[-2:])
                        bits.append(f"{tail}: {e.get('fetched', 0)}/"
                                    f"{e.get('total', '?')}")
                    sample_note += (("; " if sample_note else "")
                                    + "per-layer " + "; ".join(bits))
                layers.append(feature_collection(
                    out.get("features", []),
                    dataset=out.get("dataset", ""),
                    title=step.id.replace("_", " ").title(),
                    description=sample_note,
                    geometry_type=out.get("geometry_type", ""),
                    role="primary" if is_final else "context",
                    style=out.get("style"),
                    choropleth=out.get("choropleth"),
                ))
                if out.get("dataset"):
                    datasets.append(out["dataset"])
                for s in out.get("sources", []):
                    if s not in sources:
                        sources.append(s)
            elif isinstance(out, dict) and out.get("type") == "map_layers":
                for i, named in enumerate(out.get("layers", [])):
                    layers.append(feature_collection(
                        named.get("features", []),
                        dataset=named.get("title", ""),
                        title=named.get("title", f"layer_{i}"),
                        role="primary",
                    ))
                    datasets.append(named.get("title", ""))
            elif isinstance(out, dict) and out.get("type") == "download":
                downloads.append({
                    "filename": out.get("filename"),
                    "mime": out.get("mime"),
                    "count": out.get("count"),
                    "content": out.get("content"),
                    "from_step": step.id,
                })
            elif isinstance(out, dict) and out.get("type") == "table":
                datasets.append(out.get("dataset", step.tool))
                note = (
                    f"{step.id}: {out.get('row_count', 0)} rows "
                    f"({', '.join(out.get('columns', [])[:6])})"
                )
                # Small tables are safe to inline so LLM explanations can
                # quote actual numbers instead of describing the shape.
                if out.get("row_count", 0) <= 10 and out.get("rows"):
                    note += f" values={json.dumps(out['rows'][:10])}"
                table_notes.append(note)
                # Transport-safe copy for download/analysis modes (capped).
                rows = out.get("rows", []) or []
                tables.append({
                    "id": step.id,
                    "title": step.id.replace("_", " ").title(),
                    "dataset": out.get("dataset", step.tool),
                    "columns": out.get("columns", []),
                    "rows": rows[:MAX_TABLE_ROWS],
                    "row_count": out.get("row_count", len(rows)),
                    "truncated": len(rows) > MAX_TABLE_ROWS,
                })
        # Table outputs become citable [T#] sources so combined answers can
        # quote measured values (labels match the prompt block built in agent).
        for i, t in enumerate(tables, 1):
            references.append({
                "ref": f"T{i}",
                "source": t.get("dataset"),
                "title": f"Table: {t.get('title')}",
                "identifier": t.get("dataset"),
                "url": None,
            })

        for step in plan.steps:
            if not store.has(step.id):
                continue
            out = store.get(step.id)
            if isinstance(out, dict) and out.get("type") == "knowledge":
                for h in out.get("hits", []):
                    # Global renumbering: refs are unique across all knowledge
                    # steps so [S#] markers in the answer resolve unambiguously.
                    ref_counter += 1
                    ref = f"S{ref_counter}"
                    entry = {
                        "ref": ref,
                        "source": h.get("source"), "title": h.get("title"),
                        "identifier": h.get("identifier"), "url": h.get("url"),
                    }
                    sources.append(entry)
                    references.append({**entry, "passage": h.get("passage", "")})

        # Final GIS layer = output of the last FeatureCollection-producing step.
        primary_count = layers[-1]["metadata"]["count"] if layers else None
        status = "completed" if not fatal or layers or table_notes or downloads else "failed"
        explanation = self._explain(plan, layers, table_notes, sources, fatal)
        if truncation_warnings:
            explanation += " Warning: " + " ".join(truncation_warnings)
        if mocked:
            explanation += (
                " Note: "
                + ", ".join(sorted(set(mocked)))
                + " feature(s) are mock-backed fixtures (live ArcGIS servers "
                "unreachable); geometry and attributes are provisional, not "
                "real county records."
            )
        error = None
        if fatal and not (layers or table_notes):
            error = {"code": "processing_error",
                     "message": "Execution failed.",
                     "detail": "; ".join(e.get("error", "") for e in fatal),
                     "hint": "Retry, narrow the query, or check data-source configuration."}
            status = "failed"

        return build_final_response(
            query_id=query_id, status=status, explanation=explanation,
            results=layers or None,
            dataset=", ".join(dict.fromkeys(datasets)),
            count=primary_count,
            sources=sources or None,
            references=references or None,
            tables=tables or None,
            downloads=downloads or None,
            execution={"plan": {"goal": plan.goal,
                                "steps": [s.model_dump() for s in plan.steps]},
                       "selected_tools": sorted(set(operations)),
                       "data_sources": sorted(set(datasets)),
                       "tool_calls": tool_calls,
                       "execution_time_ms": execution_ms,
                       "errors": errors,
                        "table_notes": table_notes,
                        "mocked_datasets": sorted(set(mocked)),
                        "truncation_warnings": truncation_warnings,
                       "knowledge_hits": sum(1 for s in sources if s.get("identifier"))},
        )

    @staticmethod
    def _explain(plan, layers, table_notes, sources, errors) -> str:
        parts = [f"Goal: {plan.goal}."]
        for layer in layers:
            md = layer["metadata"]
            seg = (f"{md['title']}: {md['count']} features "
                   f"({md.get('dataset', '')}).".strip())
            if md.get("description"):
                seg += f" [{md['description']}]"
            parts.append(seg)
        parts.extend(table_notes)
        if sources:
            titles = [s.get("title") or s.get("source") or s.get("dataset")
                      or s.get("url") for s in sources[:5]]
            titles = list(dict.fromkeys(t for t in titles if t))
            if titles:
                parts.append("Sources: " + "; ".join(titles) + ".")
        for e in errors:
            parts.append(f"Step '{e.get('step')}' failed: {e.get('error')}.")
        # A zero intersect over sampled heads is "no overlap in the sample",
        # not proof of zero county-wide — say so instead of a bare 0.
        if (layers and layers[-1]["metadata"].get("count") == 0
                and any(l["metadata"].get("description", "").startswith("sampled")
                        for l in layers)):
            parts.append("0 intersections in the sampled subsets; "
                         "narrow with a place name or bbox for a full-county check.")
        return " ".join(p for p in parts if p)
