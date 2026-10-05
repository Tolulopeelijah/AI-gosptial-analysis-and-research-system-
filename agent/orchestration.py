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
                # Provisional role; the true primary (the answer) is decided
                # after the loop (a "near" step beats plan order, which puts
                # the reference layer last in RulePlanner proximity plans).
                is_final = step.id in ("result", "sample")
                warning = out.get("truncation_warning")
                if warning and warning not in truncation_warnings:
                    truncation_warnings.append(warning)
                # --- user-facing layer subtitle: short, human-friendly ---
                human_bits: List[str] = []
                if out.get("truncated"):
                    total = out.get("total_count")
                    if total:
                        human_bits.append(
                            f"showing first {out.get('count', 0)} of {total}")
                    else:
                        human_bits.append(
                            f"showing first {out.get('count', 0)}")
                if out.get("layer_errors"):
                    human_bits.append("part of this layer failed to load")
                puc = out.get("per_url_counts") or []
                partial = [e for e in puc
                           if (e.get("total") or 0) > 0 and not e.get("fetched")]
                if puc and (len(puc) > 1 and (partial or len(puc) > 1)):
                    # Only hint at partial coverage in the subtitle; full
                    # per-URL counts stay in execution diagnostics.
                    fetched = sum(e.get("fetched", 0) or 0 for e in puc)
                    total_p = sum(e.get("total", 0) or 0 for e in puc)
                    if total_p > fetched:
                        human_bits.append(
                            f"partial coverage ({fetched} of {total_p} loaded)")
                sample_note = " · ".join(human_bits)
                # --- full technical diagnostics: kept out of the subtitle,
                # forwarded in execution + layer metadata instead ---
                diagnostics: List[str] = []
                for le in (out.get("layer_errors") or [])[:3]:
                    diagnostics.append(str(le)[:500])
                if puc:
                    for e in puc:
                        tail = "/".join(
                            str(e.get("url") or "").rstrip("/").split("/")[-2:])
                        diagnostics.append(
                            f"{tail}: fetched={e.get('fetched', 0)} "
                            f"total={e.get('total', '?')}")
                layer = feature_collection(
                    out.get("features", []),
                    dataset=out.get("dataset", ""),
                    title=step.id.replace("_", " ").title(),
                    description=sample_note,
                    geometry_type=out.get("geometry_type", ""),
                    role="primary" if is_final else "context",
                    style=out.get("style"),
                    choropleth=out.get("choropleth"),
                )
                layer["metadata"]["step_id"] = step.id
                if diagnostics:
                    layer["metadata"]["diagnostics"] = diagnostics
                    # Mark partial coverage for the explanation builder.
                    if out.get("layer_errors") or partial:
                        layer["metadata"]["partial"] = True
                if out.get("truncated"):
                    layer["metadata"]["sampled"] = True
                    if out.get("total_count"):
                        layer["metadata"]["total_count"] = out.get("total_count")
                layers.append(layer)
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

        # Primary = the answer layer; the rest are context searched against.
        # RulePlanner proximity plans list the reference layer last
        # ([septic(near=floodplains), floodplains]), so "last step" alone
        # would crown the reference. Prefer: sample > result > the step
        # that carries the spatial filter (near/spatial_filter) > last layer.
        if layers:
            by_step = {l["metadata"].get("step_id"): l for l in layers}
            primary_step = None
            for candidate in ("sample", "result"):
                if candidate in by_step:
                    primary_step = candidate
                    break
            if primary_step is None:
                for step in plan.steps:
                    args = step.arguments or {}
                    if step.id in by_step and (
                            args.get("near") or args.get("spatial_filter")):
                        primary_step = step.id
            if primary_step is None and layers:
                # Fall back to the last FeatureCollection step in plan order.
                for step in reversed(plan.steps):
                    if step.id in by_step:
                        primary_step = step.id
                        break
            ordered = [l for l in layers
                       if l["metadata"].get("step_id") != primary_step]
            primary_layer = by_step.get(primary_step, layers[-1])
            ordered.append(primary_layer)
            layers = ordered
            for layer in layers[:-1]:
                layer["metadata"]["role"] = "context"
            layers[-1]["metadata"]["role"] = "primary"
        primary_count = layers[-1]["metadata"]["count"] if layers else None
        status = "completed" if not fatal or layers or table_notes or downloads else "failed"
        explanation = self._explain(
            plan, layers, tables, table_notes, sources, fatal,
            mocked=sorted(set(mocked)),
            truncation_warnings=truncation_warnings,
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
                        "layer_diagnostics": {
                            (l["metadata"].get("title") or "layer"): l["metadata"].get(
                                "diagnostics", [])
                            for l in layers
                            if l["metadata"].get("diagnostics")},
                       "knowledge_hits": sum(1 for s in sources if s.get("identifier"))},
        )

    @staticmethod
    def _pretty_dataset(name: str) -> str:
        pretty = {
            "septic_systems": "septic systems",
            "floodplains": "floodplain areas",
            "maumee_water_quality": "Maumee water-quality records",
        }
        if not name:
            return "matching features"
        if name in pretty:
            return pretty[name]
        return name.replace("_", " ")

    @classmethod
    def _pretty_dataset_n(cls, n: int, name: str) -> str:
        """Count + correctly pluralised dataset name ('1 septic system')."""
        singular_plural = {
            "septic_systems": ("septic system", "septic systems"),
            "floodplains": ("floodplain area", "floodplain areas"),
            "maumee_water_quality": (
                "Maumee water-quality record", "Maumee water-quality records"),
        }
        if name in singular_plural:
            word = singular_plural[name][0] if n == 1 else singular_plural[name][1]
        else:
            base = cls._pretty_dataset(name)
            word = base[:-1] if (n == 1 and base.endswith("s")) else base
        return f"{n} {word}"

    @classmethod
    def _explain(cls, plan, layers, tables, table_notes, sources, errors,
                 mocked=None, truncation_warnings=None) -> str:
        """Professional, plain-language summary of the results.

        Written for a non-technical audience: no service URLs, step ids,
        or debug dumps. Technical diagnostics (per-URL counts, raw service
        errors) stay in ``execution`` / layer ``metadata.diagnostics``.
        """
        mocked = mocked or []
        truncation_warnings = truncation_warnings or []
        sentences: List[str] = []

        def plural(n: int, singular: str, plural_form: str = "") -> str:
            return singular if n == 1 else (plural_form or singular + "s")

        # ---- GIS layers ----
        if layers:
            # Independent fetches (no sample/result/spatial filter in the
            # plan, e.g. "show septic systems" which loads both layers for
            # the map): report every layer equally instead of crowning the
            # last one as the answer.
            steps = getattr(plan, "steps", []) or []
            spatial_signal = any(
                (s.id in ("sample", "result"))
                or ((s.arguments or {}).get("near")
                    or (s.arguments or {}).get("spatial_filter"))
                for s in steps)
            if not spatial_signal and len(layers) > 1:
                bits = [
                    cls._pretty_dataset_n(
                        (l["metadata"] or {}).get("count", 0),
                        (l["metadata"] or {}).get("dataset", ""))
                    for l in layers]
                sentences.append(
                    f"The analysis found {' and '.join(bits)}. "
                    f"The results are displayed on the map.")
                all_meta = [l["metadata"] for l in layers]
                if any(m.get("sampled") for m in all_meta):
                    sentences.append(
                        "These are sample results. Please specify "
                        "a smaller area to view additional records.")
                elif any(m.get("partial") for m in all_meta):
                    sentences.append(
                        "Note: a portion of the map data could not be "
                        "loaded, so additional records may exist.")
            else:
                primary = layers[-1]["metadata"]
                context = [l["metadata"] for l in layers[:-1]]
                primary_n = primary.get("count", 0)
                derived = not primary.get("dataset")
                # "Sample"/"Result" step titles mean nothing to users —
                # describe what the layer actually is instead.
                if not derived:
                    what = cls._pretty_dataset(primary.get("dataset", ""))
                    what_n = cls._pretty_dataset_n(
                        primary_n, primary.get("dataset", ""))
                elif context:
                    what = cls._pretty_dataset(context[-1].get("dataset", ""))
                    what_n = (f"{primary_n} matching feature" if primary_n == 1
                              else f"{primary_n} matching features")
                else:
                    what = "matching features"
                    what_n = (f"{primary_n} matching feature" if primary_n == 1
                              else f"{primary_n} matching features")

                if primary_n == 0:
                    if context:
                        bits = [
                            cls._pretty_dataset_n(
                                c.get("count", 0), c.get("dataset", ""))
                            for c in context]
                        sentences.append(
                            f"No {what} matching the search criteria were found "
                            f"after reviewing {' and '.join(bits)}.")
                    else:
                        sentences.append(
                            f"No {what} matching the search criteria were found.")
                    # Sampled-zero is "no overlap in the sample", not proof
                    # of zero county-wide.
                    if primary.get("sampled") or any(
                            c.get("sampled") for c in context):
                        sentences.append(
                            "This reflects the portion of data available for "
                            "review. Please specify a place name or map area "
                            "for a more complete assessment.")
                    elif primary.get("partial") or any(
                            c.get("partial") for c in context):
                        sentences.append(
                            "A portion of the map data could not be loaded. "
                            "Please try again or refine the search "
                            "to a smaller area.")
                else:
                    sentences.append(
                        f"The analysis found {what_n}. "
                        f"The results are displayed on the map.")
                    others = ([c for c in context] if derived else
                              [c for c in context
                               if c.get("dataset") != primary.get("dataset")])
                    if others:
                        bits = [
                            cls._pretty_dataset_n(
                                c.get("count", 0), c.get("dataset", ""))
                            for c in others]
                        sentences.append(
                            f"The search reviewed {' and '.join(bits)}.")
                    if primary.get("sampled"):
                        total = primary.get("total_count")
                        if total:
                            sentences.append(
                                f"This represents the first {primary_n} of "
                                f"approximately {total} records. Please specify "
                                f"a smaller area to view additional records.")
                        else:
                            sentences.append(
                                "These are sample results. Please specify "
                                "a smaller area to view additional records.")
                    elif primary.get("partial"):
                        sentences.append(
                            "Note: a portion of the layer could not be loaded, "
                            "so additional records may exist.")
        # ---- tables ----
        for t in (tables or []):
            title = (t.get("title") or "").strip() or "Result"
            rows = t.get("rows", []) or []
            cols = t.get("columns", []) or []
            n = t.get("row_count", len(rows))
            # A count table already states its headline value in its rows
            # (metric=count); report that value instead of the row count so
            # it does not duplicate or contradict the layer sentence above.
            if ((t.get("id") or "").lower() == "count"
                    or title.lower() == "count") and rows:
                total = next(
                    (r.get("value") for r in rows
                     if isinstance(r, dict) and r.get("metric") == "count"),
                    None)
                if total is not None:
                    sentences.append(f"The total count is {total}.")
                    continue
            if n == 0:
                sentences.append(f"The {title.lower()} contains no records.")
            elif n == 1 and rows and isinstance(rows[0], dict):
                # Quote the single row's key facts in plain language.
                facts = ", ".join(
                    f"{k} is {v}" for k, v in list(rows[0].items())[:4])
                sentences.append(
                    f"The {title.lower()} contains one record ({facts}).")
            elif rows and len(cols) <= 8:
                sentences.append(
                    f"The {title.lower()} contains {n} "
                    f"{plural(n, 'record')}. Key details are provided below.")
            else:
                sentences.append(
                    f"A {title.lower()} with {n} "
                    f"{plural(n, 'record')} is included below.")
        # ---- knowledge references ----
        # A knowledge-only answer has no layers or tables, but it is still
        # an answer — say what was found instead of falling through to the
        # "no results" fallback while references print below.
        knowledge_hits = [s for s in (sources or [])
                          if str(s.get("ref", "")).startswith("S")]
        if knowledge_hits and not layers and not tables:
            sentences.append(
                f"The search found {len(knowledge_hits)} "
                f"{plural(len(knowledge_hits), 'relevant publication')}. "
                f"Key details are listed in the references below.")
        elif knowledge_hits:
            sentences.append(
                f"The search also reviewed {len(knowledge_hits)} "
                f"{plural(len(knowledge_hits), 'relevant publication')}, "
                f"listed in the references below.")
        # Fallback when there are neither layers, tables, nor references
        # (full failure is handled by the caller with status=failed).
        if not layers and not tables and not sentences:
            if errors:
                sentences.append(
                    "The requested data could not be loaded at this time.")
            else:
                sentences.append("No results are available for this request.")

        # ---- honesty notes, in plain professional language ----
        if mocked:
            what = " and ".join(
                cls._pretty_dataset(m) for m in sorted(set(mocked)))
            sentences.append(
                "Note: the county map servers were unreachable, "
                f"so the {what} presented are demonstration data, "
                "not official county records.")
        if truncation_warnings and not any(
                l["metadata"].get("sampled") for l in layers):
            sentences.append(
                "Only part of the full dataset could be loaded. "
                "Please refine the search to a smaller area "
                "for complete results.")

        # ---- step errors: plain professional language, no step ids ----
        # Raw service URLs and tracebacks stay in execution metadata.
        recoverable = bool(layers or tables)
        for e in errors or []:
            if recoverable:
                sentences.append(
                    "Note: one part of the search encountered an issue; "
                    "the available results are presented above.")
                break
            sentences.append(
                "The search could not be completed. Please try again "
                "or refine the search to a smaller area.")
            break

        text = " ".join(s.strip() for s in sentences if s and s.strip())
        # Safety net: never return the old debug-dump style even if a future
        # caller passes something unexpected.
        return text.strip() or "The results are presented on the map with details below."
