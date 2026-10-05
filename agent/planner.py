"""Query understanding + structured planning.

Two planners, one interface:

* OpenAIPlanner — calls the configured OpenAI model with structured outputs
  (JSON schema) + tool definitions for function calling. Used when
  OPENAI_API_KEY is set.
* RulePlanner — deterministic fallback covering the demo query shapes
  (dataset listing, Maumee summary, septic/floodplain intersect + buffer,
  knowledge search). Used offline and in tests.

Both emit a validated :class:`ExecutionPlan`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .plans import ExecutionPlan, PlanStep, validate_plan
from .registry import available_datasets, build_registry

log = logging.getLogger(__name__)

def _known_tools() -> set:
    """Live tool names from the registry (single source of truth)."""
    from .tools.registry import build_tool_registry

    return set(build_tool_registry().names())


def _ref_consuming_tools() -> set:
    """Tools whose FeatureCollection inputs arrive via $step_id references.

    Computed from registry metadata so the validator tracks new tools
    automatically; a step using one needs dependencies or $ inputs.
    """
    from .tools.registry import build_tool_registry

    reg = build_tool_registry()
    return {n for n in reg.names()
            if reg.get(n).metadata()["input_type"] == "FeatureCollection"
            and n not in ("create_map_result",)}

PLAN_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "kind": {"type": "string"},
        "unsupported_reason": {"type": ["string", "null"]},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "tool": {"type": "string"},
                    "arguments": {"type": "object"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "tool", "arguments", "depends_on"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["goal", "steps"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the planner for a natural-language geospatial agent.
Decompose the user query into steps, each executable by exactly one available tool.
Rules:
- Use ONLY the listed tool names and dataset names.
- GIS tools consume prior results via "$step_id" references (e.g. "input": "$floodplains").
- The tool list below is the full catalogue (one line each); 15 core tools also
  have full schemas attached. Prefer catalogue tools over improvisation; the
  discover_tools/search_tools/get_tool_metadata tools can inspect the catalogue
  from inside a plan when the right capability is unclear.
- query_arcgis retrieves features, with optional server-side spatial filter
  ("near": "$other_step", "distance_km": N, or equivalently
  "spatial_filter": {"reference": "$other_step"|"dataset_name",
  "relationship": "within_distance"|"intersects", "distance": N,
  "units": "meters"}); buffer/intersect/nearest process
  in-memory results and non-ArcGIS data only.
- For ArcGIS-to-ArcGIS proximity (e.g. septic systems near floodplains) use a
  two-step plan — fetch the reference layer, then query the target with
  "near" + "distance_km" — never fetch-then-buffer-then-intersect, which
  silently drops matches outside the max_features cap. A single-step
  "spatial_filter" with a dataset-name reference is also accepted; the tool
  paginates and resolves the reference server-side.
- query_arcgis pages automatically: "page_size" is the per-request service
  page (default 1000, max 2000); "max_features" is the total intent per
  layer URL (default 1000; larger values page to completion up to a safety
  ceiling, truncation always reported). Prefer server-side spatial filtering
  over raising max_features to download whole counties.
- For county-wide septic/floodplain fetches pass "max_features": 2000
  (default analysis window); results still report total vs sampled counts.
- query_maumee answers tabular water-quality questions (no per-row geometry exists).
- search_knowledge_base answers publication/science questions.
- Every step needs "id", "tool", "arguments" (a JSON object of actual values), and "depends_on" (a JSON array of step ids, possibly empty).
- "kind" must be one of: gis, knowledge, combined, unsupported.
- If the query needs unavailable data or operations, output "kind": "unsupported", a non-empty "unsupported_reason", and "steps": [].
- Output a JSON plan INSTANCE with real values, never a schema. Example:
{"goal": "Find septic systems within 2 km of floodplain areas", "kind": "combined",
 "unsupported_reason": "",
 "steps": [
  {"id": "floodplains", "tool": "query_arcgis", "arguments": {"dataset": "floodplains", "max_features": 2000}, "depends_on": []},
  {"id": "septic", "tool": "query_arcgis", "arguments": {"dataset": "septic_systems", "max_features": 2000, "near": "$floodplains", "distance_km": 2}, "depends_on": ["floodplains"]},
  {"id": "kb", "tool": "search_knowledge_base", "arguments": {"query": "phosphorus water-quality implications"}, "depends_on": []}
 ]}
Respond with ONLY the JSON plan object."""

# Full function schemas are sent for these core tools only; the other ~105
# tools are described in one compact line each (name, category, use, key
# arguments) so planning stays within context while keeping the whole
# toolbox addressable. Plans may name any catalogued tool — structure is
# enforced afterwards by validate_plan.
CORE_SCHEMA_TOOLS = [
    "query_arcgis", "query_maumee", "query_user_dataset", "buffer",
    "intersect", "nearest", "spatial_join", "filter_features",
    "search_datasets", "search_knowledge_base", "list_datasets",
    "describe_dataset", "discover_tools", "search_tools", "get_tool_metadata",
]


def _compact_catalog() -> List[str]:
    """One line per tool from live registry metadata (no full schemas)."""
    from .tools.registry import build_tool_registry

    reg = build_tool_registry()
    lines = []
    for name in reg.names():
        meta = reg.get(name).metadata()
        args = ", ".join(
            (a + "*") if a in meta["required"] else a
            for a in meta["arguments"]) or "no arguments"
        net = " [network]" if meta["network"] else ""
        lines.append(
            f"- {meta['name']} ({meta['category']}){net}: "
            f"{meta['description']} | args: {args}")
    return lines


class OpenAIPlanner:
    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key

    def plan(self, query: str, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        from openai import OpenAI

        from .tools.registry import build_tool_registry

        registry = build_registry()
        tool_registry = build_tool_registry()
        tool_defs = [t.openai_definition() for n, t in
                     ((n, tool_registry.get(n)) for n in CORE_SCHEMA_TOOLS)
                     if t is not None]
        lines = ["TOOLS (all addressable by name — full schemas above for core tools only):",
                 *_compact_catalog()]
        lines.append("DATASETS (name | available | access):")
        for d in ({"name": n, "description": dd.description,
                   "available": dd.available, "access": dd.access_method}
                  for n, dd in registry.items()):
            lines.append(
                f"- {d['name']} | available={d['available']} | via {d['access']} — {d['description']}"
            )
        client = OpenAI(api_key=self.api_key)
        user = "\n".join(lines) + f"\n\nUSER QUERY: {query}"
        if history:
            convo = "\n".join(
                f"{'User' if h.get('role') == 'user' else 'Assistant'}: "
                f"{h.get('content', '')[:400]}" for h in history[-4:])
            user += ("\n\nConversation so far (resolve follow-ups like "
                     f"'it', 'that', 'what about' against it):\n{convo}")
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                tools=tool_defs,  # advertised so the model picks real tools
                tool_choice="none",
                # Plain JSON mode: the response_format schema hint is NOT
                # used because non-strict schemas are unenforced and the
                # schema vocabulary primes small models to echo schemas.
                # Structure is enforced afterwards by _finalize/validate_plan.
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
        except Exception as exc:
            log.warning("OpenAI planning failed, falling back to rules: %s", exc)
            return RulePlanner().plan(query)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("OpenAI planning returned non-JSON, falling back to rules")
            return RulePlanner().plan(query)
        try:
            return self._finalize(query, data)
        except Exception as exc:
            log.warning("OpenAI plan invalid (%s), falling back to rules", exc)
            return RulePlanner().plan(query)

    def _finalize(self, query: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
            raise ValueError("planner output is not a plan object")
        registry = build_registry()
        known_tools = _known_tools()
        raw_steps = data.get("steps", [])
        for s in raw_steps:
            args = (s.get("arguments") if isinstance(s, dict) else None) or {}
            if isinstance(args, dict) and ("properties" in args or "$schema" in args):
                raise ValueError("planner echoed a schema instead of values")
        steps = [PlanStep(**s) for s in raw_steps]
        if not steps:
            return {
                "plan": None, "kind": "unsupported",
                "reason": data.get("unsupported_reason")
                or "The model produced no executable steps for this query.",
            }
        plan = validate_plan(
            ExecutionPlan(goal=data.get("goal", query), steps=steps),
            known_tools=known_tools,
            known_datasets=set(registry),
            gis_result_tools=_ref_consuming_tools(),
        )
        # Derive kind from the tools actually used — never trust the model's
        # label. The system-prompt example is kind "combined", which models
        # otherwise copy onto pure-GIS plans; that mislabel makes agent.py
        # run the knowledge rewrite and clobber good GIS explanations.
        tools_used = {s.tool for s in steps}
        if tools_used == {"search_knowledge_base"}:
            kind = "knowledge"
        elif "search_knowledge_base" in tools_used:
            kind = "combined"
        else:
            kind = "gis"
        return {"plan": plan, "kind": kind, "reason": ""}


# ------------------------------------------------- rule-based fallback ---

# Full unit names first (longest match wins) with a word boundary, so
# "5 miles" captures "miles" — not "m" — and short codes need the boundary
# so "mi"/"m" don't match stray substrings.
_DISTANCE_RE = re.compile(
    r"within\s+([\d.]+)\s*(kilometers?|kilometres?|miles?|meters?|metres?|feet|foot|km|mi|m|ft)\b",
    re.I,
)
_MAUMEE_RE = re.compile(
    r"\b(maumee|phosphorus|phosphate|nitrate|nitrite|nitrogen|kjeldahl|"
    r"chloride|sulfate|sulphate|silica|solids|sediment|dissolved|soluble|"
    r"tss|srp|no23|tkn|cond|flow|discharge|conductivity|water quality)\b", re.I)
_EXTREMES_RE = re.compile(
    r"\b(highest|lowest|maximum|minimum|peak|all-time|all time)\b"
    r"|\brecord\s+(high|low)\b|\bwhen was\b|\bwhat day\b|\bwhich date\b", re.I)

# Full parameter names first (longest match wins); short codes need word
# boundaries so "flow" doesn't fire inside "follow".
_PARAM_NAMES = [
    ("total suspended solids", "TSS"), ("suspended solids", "TSS"),
    ("suspended sediment", "TSS"),
    ("soluble reactive phosphorus", "SRP"),
    ("dissolved reactive phosphorus", "SRP"),
    ("dissolved phosphorus", "SRP"), ("soluble phosphorus", "SRP"),
    ("total phosphorus", "TP"), ("nitrite + nitrate", "NO23"),
    ("nitrite+nitrate", "NO23"),
    ("phosphorus", "TP"), ("phosphate", "TP"), ("sediment", "TSS"),
    ("nitrite", "NO23"), ("nitrate", "NO23"), ("nitrogen", "NO23"),
    ("kjeldahl", "TKN"), ("chloride", "CL"), ("sulfate", "SO4"),
    ("sulphate", "SO4"), ("silica", "SI"), ("conductivity", "COND"),
    ("discharge", "FLOW"), ("dissolved", "SRP"), ("soluble", "SRP"),
    ("flow", "FLOW"),
]
_KNOW_RE = re.compile(r"\b(publication|research|paper|stud(y|ies)|implication|ncwqr|literature|wqr)\b", re.I)
_SEPTIC_RE = re.compile(r"\bseptic\b", re.I)
_FLOOD_RE = re.compile(r"\bfloodplain|flood\b", re.I)
_HOSPITAL_RE = re.compile(r"\bhospital|school|restaurant|earthquake|wildfire|hurricane\b", re.I)


class RulePlanner:
    """Deterministic planner for known query shapes; honest 'unsupported'
    for anything else (never invents tools or datasets)."""

    def plan(self, query: str, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        q = query.strip()
        registry = build_registry()
        avail = set(available_datasets(registry))
        wants_knowledge = bool(_KNOW_RE.search(q))
        wants_maumee = bool(_MAUMEE_RE.search(q)) and not _SEPTIC_RE.search(q)
        wants_septic = bool(_SEPTIC_RE.search(q))
        wants_flood = bool(_FLOOD_RE.search(q))

        if _HOSPITAL_RE.search(q):
            m = _HOSPITAL_RE.search(q)
            return {"plan": None, "kind": "unsupported",
                    "reason": f"No dataset containing {m.group(0).lower()} locations is available. "
                    f"Available datasets: {sorted(avail)}."}
        if wants_septic and "septic_systems" not in avail:
            return {"plan": None, "kind": "unsupported",
                    "reason": "The septic-systems ArcGIS layer URL is not configured "
                    "(ARCGIS_SEPTIC_URL). I can describe the limitation but cannot retrieve the data."}
        if wants_flood and "floodplains" not in avail:
            return {"plan": None, "kind": "unsupported",
                    "reason": "No floodplain ArcGIS layer URL is configured "
                    "(ARCGIS_FLOODPLAIN_0_URL / ARCGIS_FLOODPLAIN_4_URL)."}

        steps: List[PlanStep] = []
        kind = "gis"
        user_match = self._user_dataset_match(q.lower(), registry)
        if user_match:
            steps = self._user_data_steps(
                q, user_match, registry, avail, wants_septic, wants_flood,
                wants_knowledge)
            if any(s.tool == "search_knowledge_base" for s in steps):
                kind = "combined"
        elif re.search(r"\bhow many\b", q, re.I) and (wants_septic or wants_flood):
            target, ds = (("septic", "septic_systems") if wants_septic
                          else ("floodplains", "floodplains"))
            steps = [PlanStep(id=target, tool="query_arcgis",
                              arguments={"dataset": ds}, depends_on=[]),
                     PlanStep(id="count", tool="count_features",
                              arguments={"input": f"${target}"},
                              depends_on=[target])]
        elif re.search(r"\b(area|how large|how big|total size)\b", q, re.I) and wants_flood:
            steps = [PlanStep(id="floodplains", tool="query_arcgis",
                              arguments={"dataset": "floodplains"}, depends_on=[]),
                     PlanStep(id="area", tool="calculate_area",
                              arguments={"input": "$floodplains", "unit": "sqkm"},
                              depends_on=["floodplains"])]
        elif wants_maumee and not (wants_septic or wants_flood):
            param = self._param(q)
            operation = "extremes" if _EXTREMES_RE.search(q) else "summary"
            steps = [PlanStep(id="maumee", tool="query_maumee",
                              arguments={"operation": operation,
                                         **({"parameter": param} if param else {})},
                              depends_on=[])]
            kind = "knowledge" if wants_knowledge else "gis"
            if wants_knowledge:
                steps.append(PlanStep(id="kb", tool="search_knowledge_base",
                                      arguments={"query": q}, depends_on=[]))
                kind = "combined"
        elif wants_septic or wants_flood:
            if "septic_systems" in avail:
                steps.append(PlanStep(id="septic", tool="query_arcgis",
                                      arguments={"dataset": "septic_systems",
                                                 "max_features": 2000},
                                      depends_on=[]))
            if "floodplains" in avail:
                steps.append(PlanStep(id="floodplains", tool="query_arcgis",
                                      arguments={"dataset": "floodplains",
                                                 "max_features": 2000},
                                      depends_on=[]))
            dist = _DISTANCE_RE.search(q)
            needs_gis = ("intersect" in q.lower() or " in " in f" {q.lower()} "
                         or "within" in q.lower() or "near" in q.lower()
                         or (wants_septic and wants_flood))
            if dist and "floodplains" in avail and "septic_systems" in avail:
                # Server-side proximity: filter septic systems at the
                # source against the floodplain geometries instead of
                # fetching the first 2000 rows and intersecting locally
                # (which silently misses matches outside the cap).
                val, unit = float(dist.group(1)), dist.group(2).lower()
                for s in steps:
                    if s.id == "septic":
                        s.arguments = {
                            **s.arguments,
                            "near": "$floodplains",
                            "distance_km": self._to_km(val, unit),
                        }
                        if "floodplains" not in s.depends_on:
                            s.depends_on = [*s.depends_on, "floodplains"]
            elif dist and "floodplains" in avail:
                val, unit = float(dist.group(1)), dist.group(2).lower()
                steps.append(PlanStep(
                    id="buffer", tool="buffer",
                    arguments={"input": "$floodplains", "distance": val,
                               "unit": self._norm_unit(unit)},
                    depends_on=["floodplains"]))
            elif needs_gis and wants_septic and wants_flood:
                steps.append(PlanStep(
                    id="result", tool="intersect",
                    arguments={"input_a": "$septic", "input_b": "$floodplains"},
                    depends_on=["septic", "floodplains"]))
            if wants_knowledge:
                steps.append(PlanStep(id="kb", tool="search_knowledge_base",
                                      arguments={"query": q}, depends_on=[]))
                kind = "combined"
        elif wants_knowledge or "dataset" in q.lower():
            if re.search(r"\b(list|what|which|available)\b.*\bdataset", q, re.I):
                steps = [PlanStep(id="datasets", tool="list_datasets",
                                  arguments={}, depends_on=[])]
            else:
                steps = [PlanStep(id="kb", tool="search_knowledge_base",
                                  arguments={"query": q}, depends_on=[])]
                kind = "knowledge"
        else:
            return {"plan": None, "kind": "unsupported",
                    "reason": f"I could not map this query to an available tool/dataset. "
                    f"Available datasets: {sorted(avail)}. "
                    "Supported: septic/floodplain GIS analysis, Maumee water-quality summaries, NCWQR knowledge search."}

        if not steps:
            return {"plan": None, "kind": "unsupported",
                    "reason": "No executable steps could be derived from this query."}
        plan = validate_plan(
            ExecutionPlan(goal=q, steps=steps),
            known_tools=_known_tools(),
            known_datasets=set(registry),
            gis_result_tools=_ref_consuming_tools(),
        )
        return {"plan": plan, "kind": kind, "reason": ""}

    @staticmethod
    def _user_dataset_match(query_lower: str, registry) -> Optional[str]:
        """Match an uploaded dataset by its registered name."""
        for name, info in registry.items():
            if info.source_type != "user_upload" or not info.available:
                continue
            spoken = name.replace("_", " ")
            if spoken in query_lower or name in query_lower.replace(" ", "_"):
                return name
        return None

    def _user_data_steps(self, q: str, dataset: str, registry, avail,
                         wants_septic: bool, wants_flood: bool,
                         wants_knowledge: bool) -> List[PlanStep]:
        """Retrieval of an uploaded dataset, optionally intersected/buffered
        against one other spatial dataset using the same pattern as the
        built-in septic/floodplain branch."""
        steps = [PlanStep(id="user_data", tool="query_user_dataset",
                          arguments={"dataset": dataset}, depends_on=[])]
        others = []
        if wants_septic and "septic_systems" in avail:
            others.append(("septic", "septic_systems"))
        if wants_flood and "floodplains" in avail:
            others.append(("floodplains", "floodplains"))
        for oid, ds in others:
            steps.append(PlanStep(id=oid, tool="query_arcgis",
                                  arguments={"dataset": ds}, depends_on=[]))
        if others:
            dist = _DISTANCE_RE.search(q)
            needs_gis = ("intersect" in q.lower() or "near" in q.lower()
                         or "within" in q.lower())
            oid = others[0][0]
            if dist:
                val, unit = float(dist.group(1)), dist.group(2).lower()
                steps.append(PlanStep(
                    id="buffer", tool="buffer",
                    arguments={"input": f"${oid}", "distance": val,
                               "unit": self._norm_unit(unit)},
                    depends_on=[oid]))
                steps.append(PlanStep(
                    id="result", tool="intersect",
                    arguments={"input_a": "$user_data", "input_b": "$buffer"},
                    depends_on=["user_data", "buffer"]))
            elif needs_gis:
                steps.append(PlanStep(
                    id="result", tool="intersect",
                    arguments={"input_a": "$user_data", "input_b": f"${oid}"},
                    depends_on=["user_data", oid]))
        if wants_knowledge:
            steps.append(PlanStep(id="kb", tool="search_knowledge_base",
                                  arguments={"query": q}, depends_on=[]))
        return steps

    @staticmethod
    def _param(q: str) -> str | None:
        ql = q.lower()
        for name, code in _PARAM_NAMES:
            if len(name) <= 7:
                # Short words ("flow", "silica" is fine, but guard) match on
                # word boundaries so "flow" doesn't fire inside "follow".
                if re.search(r"\b" + re.escape(name) + r"\b", ql):
                    return code
            elif name in ql:
                return code
        for code in ["TSS", "SRP", "NO23", "TKN", "COND", "FLOW", "TP", "CL", "SO4", "SI"]:
            if re.search(r"\b" + code.lower() + r"\b", ql):
                return code
        return None

    @staticmethod
    def _norm_unit(unit: str) -> str:
        unit = unit.lower()
        if unit.startswith("km") or unit.startswith("kilom"):
            return "kilometers"
        if unit in ("m", "meter", "meters", "metre", "metres"):
            return "meters"
        if unit.startswith("mile") or unit == "mi":
            return "miles"
        if unit in ("feet", "foot", "ft"):
            return "feet"
        return "meters"

    @staticmethod
    def _to_km(value: float, unit: str) -> float:
        """Raw distance phrase -> kilometres for query_arcgis distance_km."""
        unit = unit.lower()
        if unit.startswith("km") or unit.startswith("kilom"):
            return value
        if unit.startswith("mile") or unit == "mi":
            return value * 1.609344
        if unit in ("feet", "foot", "ft"):
            return value * 0.3048 / 1000.0
        return value / 1000.0  # metres and friends


def make_planner():
    from .config import settings

    if settings.OPENAI_API_KEY:
        return OpenAIPlanner(model=settings.OPENAI_MODEL, api_key=settings.OPENAI_API_KEY)
    return RulePlanner()
