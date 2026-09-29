"""Capability discovery: broad toolbox without context bloat.

The planner prompt carries one compact line per tool (name, category,
one-line use, key arguments) instead of ~120 full schemas. These three tools
let plans — and operators — inspect the catalogue on demand, and power the
machine-readable manifest (scripts/generate_tool_manifest.py).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .common import ToolError, table
from . import Tool


def _registry():
    from .registry import build_tool_registry

    return build_tool_registry()


def discover_tools(category: str = ""):
    """List tools, optionally filtered to one category, with one-line uses."""
    tools = sorted(_registry()._tools.values(), key=lambda t: (t.category, t.name))
    if category:
        cats = {t.category for t in tools}
        if category not in cats:
            raise ToolError(f"unknown category '{category}'; use one of "
                            f"{', '.join(sorted(cats))}")
        tools = [t for t in tools if t.category == category]
    rows = [{"name": t.name, "category": t.category,
             "description": t.description,
             "arguments": ", ".join(sorted(t.parameters.get("properties", {})))}
            for t in tools]
    return table(["name", "category", "description", "arguments"], rows,
                 row_count=len(rows))


def search_tools(query: str, max_hits: int = 10):
    """Keyword search over tool names/descriptions/categories/arguments."""
    from .common import cap_int

    max_hits = cap_int(max_hits, 1, 50, name="max_hits")
    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", query or "") if len(t) > 1]
    if not terms:
        raise ToolError("provide a search query")
    scored = []
    for tool in _registry()._tools.values():
        hay = f"{tool.name} {tool.category} {tool.description} " \
              f"{' '.join(tool.parameters.get('properties', {}))}".lower()
        score = sum(hay.count(t) * (3 if t in tool.name.lower() else 1)
                    for t in terms)
        if score:
            scored.append((score, tool))
    scored.sort(key=lambda p: -p[0])
    rows = [{"name": t.name, "category": t.category,
             "description": t.description, "score": s}
            for s, t in scored[:max_hits]]
    return table(["name", "category", "description", "score"], rows,
                 query=query)


def get_tool_metadata(name: str):
    """Full registry record for one tool: schema, deps, costs, units."""
    tool: Tool | None = _registry().get(name)
    if tool is None:
        raise ToolError(f"unknown tool '{name}'; use discover_tools to browse")
    return {"ok": True, "tool": tool.metadata()}


DISCOVERY_SCHEMAS = {
    "discover_tools": ({"properties": {
        "category": {"type": "string",
                     "description": "Optional category filter."}}}, []),
    "search_tools": ({"properties": {
        "query": {"type": "string", "description": "e.g. 'buffer flood'."},
        "max_hits": {"type": "integer"}}}, ["query"]),
    "get_tool_metadata": ({"properties": {
        "name": {"type": "string", "description": "Tool name."}}}, ["name"]),
}
