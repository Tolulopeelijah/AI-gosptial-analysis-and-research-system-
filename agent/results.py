"""Result abstractions.

Two concepts, kept separate on purpose:

* ResultStore — internal references (`$step_id`) to intermediate tool
  outputs, so large geographic payloads never enter the LLM context and
  later tools can consume earlier outputs by reference.
* FinalResult — the merged, frontend-compatible response: GeoJSON feature
  layers + tabular summaries + textual explanation + source citations +
  execution metadata (for research observability).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

MAX_FEATURES_TO_LLM = 5  # summaries only; full payloads stay in the store


class ResultStore:
    """Maps step ids to tool outputs for `$id` reference resolution."""

    def __init__(self) -> None:
        self._results: Dict[str, Any] = {}

    def put(self, step_id: str, value: Any) -> str:
        self._results[step_id] = value
        return f"${step_id}"

    def get(self, ref: str) -> Any:
        key = ref[1:] if ref.startswith("$") else ref
        if key not in self._results:
            raise KeyError(f"unknown intermediate result '{ref}'")
        return self._results[key]

    def has(self, step_id: str) -> bool:
        return step_id in self._results

    def summary_for_llm(self, step_id: str) -> Dict[str, Any]:
        """Small, LLM-safe summary of a stored result (never full features)."""
        value = self._results.get(step_id, {})
        if not isinstance(value, dict):
            return {"step": step_id, "type": type(value).__name__}
        summary: Dict[str, Any] = {"step": step_id}
        if value.get("type") == "FeatureCollection":
            feats = value.get("features", [])
            summary.update(
                {
                    "type": "FeatureCollection",
                    "count": len(feats),
                    "sample_properties": [
                        f.get("properties", {}) for f in feats[:MAX_FEATURES_TO_LLM]
                    ],
                }
            )
        elif value.get("type") == "table":
            rows = value.get("rows", [])
            summary.update(
                {
                    "type": "table",
                    "row_count": value.get("row_count", len(rows)),
                    "columns": value.get("columns", []),
                    "sample_rows": rows[:MAX_FEATURES_TO_LLM],
                }
            )
        elif value.get("type") == "knowledge":
            summary.update(
                {
                    "type": "knowledge",
                    "hits": len(value.get("hits", [])),
                    "titles": [
                        h.get("title") for h in value.get("hits", [])[:MAX_FEATURES_TO_LLM]
                    ],
                }
            )
        else:
            summary["keys"] = list(value.keys())[:10]
        return summary


def new_query_id() -> str:
    return f"q_{uuid.uuid4().hex[:12]}"


def feature_collection(
    features: List[Dict[str, Any]],
    *,
    dataset: str = "",
    title: str = "",
    description: str = "",
    geometry_type: str = "",
    role: str = "primary",
    attributes: Optional[List[Dict[str, Any]]] = None,
    layer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A frontend-compatible GeographicResult wrapping GeoJSON."""
    result: Dict[str, Any] = {
        "id": layer_id or f"layer_{uuid.uuid4().hex[:8]}",
        "type": "FeatureCollection",
        "data": {"type": "FeatureCollection", "features": features},
        "metadata": {
            "title": title,
            "description": description,
            "count": len(features),
            "dataset": dataset,
            "geometryType": geometry_type,
            "role": role,
        },
    }
    if attributes:
        result["metadata"]["attributes"] = attributes
    return result


def build_final_response(
    *,
    query_id: str,
    status: str,
    explanation: str = "",
    results: Optional[List[Dict[str, Any]]] = None,
    dataset: str = "",
    count: Optional[int] = None,
    sources: Optional[List[Dict[str, Any]]] = None,
    references: Optional[List[Dict[str, Any]]] = None,
    execution: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
    timing_ms: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"queryId": query_id, "status": status}
    if explanation:
        payload["explanation"] = explanation
    if results is not None:
        payload["results"] = results
    if dataset:
        payload["dataset"] = dataset
    if count is not None:
        payload["count"] = count
    if sources:
        payload["sources"] = sources
    if references:
        payload["references"] = references
    if execution is not None:
        payload["execution"] = execution
    if error is not None:
        payload["error"] = error
    if timing_ms is not None:
        payload["timingMs"] = timing_ms
    return payload
