"""Research-paper output for research mode.

A paper assembles deterministically where facts allow (title, aims, data,
methods, results, limitations, reproducibility all derive from the validated
plan and execution record — the model cannot invent them) and uses one
grounded LLM call only for abstract/discussion/conclusion, under the same
[S#]/[T#] citation rules as explanations. Without an API key, those three
sections fall back to deterministic summaries clearly labelled as such.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Dict, List, Optional


def split_aims(aims: str) -> List[str]:
    import re

    parts = re.split(r"[\n;]+|\b\d+[.)]\s+", (aims or "").strip())
    return [p.strip(" .") for p in parts if p.strip(" .")]


def _human_step(step: Dict[str, Any]) -> str:
    tool, args = step.get("tool", ""), step.get("arguments", {}) or {}
    if tool == "query_arcgis":
        extra = f" (filter: {args['where']})" if args.get("where") not in (None, "1=1") else ""
        return f"Retrieved {args.get('dataset')}{extra} from its ArcGIS FeatureServer."
    if tool == "query_maumee":
        return (f"Queried Maumee water-quality records "
                f"({args.get('parameter', 'all parameters')}, {args.get('operation', 'records')}).")
    if tool == "query_user_dataset":
        return f"Retrieved user-uploaded dataset {args.get('dataset')}."
    if tool == "buffer":
        return (f"Buffered result `${args.get('input')}` by {args.get('distance')} "
                f"{args.get('unit', 'meters')} (CRS-aware metric projection).")
    if tool == "intersect":
        return (f"Intersected `${args.get('input_a')}` with `${args.get('input_b')}`.")
    if tool == "nearest":
        return f"Computed nearest features (`${args.get('input_a')}` to `${args.get('input_b')}`)."
    if tool == "search_knowledge_base":
        return "Searched the NCWQR publication index."
    return f"Ran {tool}."


def _deterministic_sections(query, aims_list, plan, response) -> Dict[str, Any]:
    exec_ = response.get("execution", {}) or {}
    layers = response.get("results") or []
    tables = response.get("tables") or []
    tool_calls = exec_.get("tool_calls", []) or []
    total_ms = exec_.get("execution_time_ms")
    data = []
    for ds in exec_.get("data_sources", []) or []:
        data.append({"dataset": ds})
    methods = [_human_step(s) for s in
               (exec_.get("plan", {}) or {}).get("steps", [])]
    timings = {c.get("step"): c.get("duration_ms") for c in tool_calls if c.get("ok")}
    results = {
        "layers": [{"title": l.get("metadata", {}).get("title"),
                    "count": l.get("metadata", {}).get("count"),
                    "dataset": l.get("metadata", {}).get("dataset")}
                   for l in layers],
        "tables": [{"title": t.get("title"), "row_count": t.get("row_count"),
                    "values": t.get("rows", [])[:6]} for t in tables],
        "findings": response.get("explanation", ""),
    }
    limitations = []
    for m in exec_.get("mocked_datasets", []) or []:
        limitations.append(
            f"{m} features are mock-backed fixtures (live servers unreachable); "
            "geometry and attributes are provisional, not real county records.")
    limitations.append(
        "Single model run: LLM planning and prose vary between runs; "
        "re-run to assess variance before citing numbers.")
    return {
        "title": f"Geospatial analysis: {query.strip()[:140]}",
        "aims": aims_list,
        "data": data,
        "methods": methods,
        "timings_ms": timings,
        "total_time_ms": total_ms,
        "results": results,
        "limitations": limitations,
        "reproducibility": {
            "query_id": response.get("queryId"),
            "planner": (exec_.get("planner") if "planner" in exec_
                        else "plan-validated pipeline"),
            "selected_tools": exec_.get("selected_tools", []),
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        },
    }


def _llm_sections(query, aims_list, draft, references, tables) -> Dict[str, str]:
    """Abstract/discussion/conclusion via one grounded call (or fallback)."""
    from .config import settings
    from .grounding import format_sources_for_prompt

    fallback = {
        "abstract": (draft or "")[:800],
        "discussion": "Discussion unavailable offline (no model configured); "
                      "see Results and References.",
        "conclusion": "Conclusion unavailable offline (no model configured); "
                      "see Results.",
        "grounded": False,
    }
    if not settings.OPENAI_API_KEY:
        return fallback
    try:
        from openai import OpenAI

        table_block = "; ".join(
            f"[T{i}] {t.get('title')}: "
            f"{json.dumps(t.get('rows', [])[:6])}" for i, t in enumerate(tables, 1))
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system",
                 "content": (
                     "Write abstract, discussion, and conclusion sections for a short "
                     "research report, using ONLY the provided findings and sources. "
                     "Every factual sentence needs its [S#]/[T#] marker; use only "
                     "listed markers; never invent publications, data, or numbers. "
                     "Reply as JSON: {\"abstract\": ..., \"discussion\": ..., "
                     "\"conclusion\": ...}."
                 )},
                {"role": "user",
                 "content": (
                     f"Research question: {query}\n"
                     f"Aims: {'; '.join(aims_list) or 'not specified'}\n"
                     f"Findings: {draft}\nTables: {table_block}\n"
                     f"Sources:\n{format_sources_for_prompt(references)}")},
            ],
            response_format={"type": "json_object"},
            max_tokens=900,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return {"abstract": data.get("abstract", ""),
                "discussion": data.get("discussion", ""),
                "conclusion": data.get("conclusion", ""),
                "grounded": True}
    except Exception:
        return fallback


def build_paper(query: str, aims: str, plan, response: Dict[str, Any]) -> Dict[str, Any]:
    from .grounding import check_markers, strip_invalid_markers

    aims_list = split_aims(aims)
    paper = _deterministic_sections(query, aims_list, plan, response)
    references = response.get("references") or []
    tables = response.get("tables") or []
    llm = _llm_sections(query, aims_list, response.get("explanation", ""),
                        [r for r in references if r.get("passage")], tables)
    valid = {r["ref"] for r in references if r.get("ref")}
    valid |= {f"T{i}" for i in range(1, len(tables) + 1)}
    for key in ("abstract", "discussion", "conclusion"):
        cleaned, _ = strip_invalid_markers(llm.get(key, ""), valid)
        llm[key] = cleaned
    check = check_markers(
        " ".join(llm.get(k, "") for k in ("abstract", "discussion", "conclusion")),
        valid)
    paper.update({
        "abstract": llm["abstract"],
        "discussion": llm["discussion"],
        "conclusion": llm["conclusion"],
        "llm_grounded": llm["grounded"],
        "references": references,
        "citation_check": {"cited": check["cited"],
                           "invalid_markers": check["invalid"]},
    })
    paper["markdown"] = render_markdown(paper)
    return paper


def render_markdown(paper: Dict[str, Any]) -> str:
    lines = [f"# {paper.get('title', '')}", ""]
    if paper.get("abstract"):
        lines += ["## Abstract", "", paper["abstract"], ""]
    if paper.get("aims"):
        lines += ["## Aims and Objectives", ""]
        lines += [f"{i}. {a}" for i, a in enumerate(paper["aims"], 1)] + [""]
    if paper.get("data"):
        lines += ["## Data", ""]
        lines += [f"- {d.get('dataset')}" for d in paper["data"]] + [""]
    if paper.get("methods"):
        lines += ["## Methods", ""]
        lines += [f"{i}. {m}" for i, m in enumerate(paper["methods"], 1)] + [""]
    res = paper.get("results", {}) or {}
    lines += ["## Results", ""]
    for layer in res.get("layers", []) or []:
        lines.append(f"- {layer.get('title')}: {layer.get('count')} features "
                     f"({layer.get('dataset')}).")
    for table in res.get("tables", []) or []:
        lines.append(f"- {table.get('title')}: {table.get('row_count')} rows.")
    if res.get("findings"):
        lines += ["", res["findings"], ""]
    if paper.get("discussion"):
        lines += ["## Discussion", "", paper["discussion"], ""]
    if paper.get("conclusion"):
        lines += ["## Conclusion", "", paper["conclusion"], ""]
    if paper.get("limitations"):
        lines += ["## Limitations", ""]
        lines += [f"- {x}" for x in paper["limitations"]] + [""]
    if paper.get("references"):
        lines += ["## References", ""]
        for r in paper["references"]:
            lines.append(f"[{r.get('ref')}] {r.get('title', '')} "
                         f"({r.get('identifier', '')}) {r.get('url') or ''}".strip())
        lines.append("")
    rep = paper.get("reproducibility", {}) or {}
    if rep:
        lines += ["## Reproducibility", "",
                  f"Query ID: {rep.get('query_id')}; tools: "
                  f"{', '.join(rep.get('selected_tools', []) or [])}; "
                  f"generated {rep.get('generated_at')}.", ""]
    return "\n".join(lines).strip() + "\n"
