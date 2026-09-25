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
    resolved = {}
    for key, value in arguments.items():
        if isinstance(value, str) and value.startswith("$"):
            resolved[key] = store.get(value)
        else:
            resolved[key] = value
    return resolved


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
            return f"{output.get('count', 0)} features loaded"
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
        datasets: List[str] = []
        operations: List[str] = []
        table_notes: List[str] = []
        mocked: List[str] = []
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
                layers.append(feature_collection(
                    out.get("features", []),
                    dataset=out.get("dataset", ""),
                    title=step.id.replace("_", " ").title(),
                    geometry_type=out.get("geometry_type", ""),
                    role="primary" if is_final else "context",
                ))
                if out.get("dataset"):
                    datasets.append(out["dataset"])
                for s in out.get("sources", []):
                    if s not in sources:
                        sources.append(s)
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
        status = "completed" if not fatal or layers or table_notes else "failed"
        explanation = self._explain(plan, layers, table_notes, sources, fatal)
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
            execution={"plan": {"goal": plan.goal,
                                "steps": [s.model_dump() for s in plan.steps]},
                       "selected_tools": sorted(set(operations)),
                       "data_sources": sorted(set(datasets)),
                       "tool_calls": tool_calls,
                       "execution_time_ms": execution_ms,
                       "errors": errors,
                       "table_notes": table_notes,
                       "mocked_datasets": sorted(set(mocked)),
                       "knowledge_hits": sum(1 for s in sources if s.get("identifier"))},
        )

    @staticmethod
    def _explain(plan, layers, table_notes, sources, errors) -> str:
        parts = [f"Goal: {plan.goal}."]
        for layer in layers:
            md = layer["metadata"]
            parts.append(f"{md['title']}: {md['count']} features "
                         f"({md.get('dataset', '')}).".strip())
        parts.extend(table_notes)
        if sources:
            titles = [s.get("title") or s.get("source") for s in sources[:5]]
            parts.append("Sources: " + "; ".join(t for t in titles if t) + ".")
        for e in errors:
            parts.append(f"Step '{e.get('step')}' failed: {e.get('error')}.")
        return " ".join(p for p in parts if p)
