"""Map output: assemble, style, classify, and export results.

These integrate with the existing frontend contract rather than inventing a
new one: `create_map_result` fans intermediate layers out into standard
FeatureCollections the map already renders; `style_layer` attaches the style
object the legend reads; `create_choropleth` attaches the graduated spec the
frontend ramps. Exports serialise result references to download payloads
(filename + MIME + text content).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..common import ToolError, collection, features_of, table


def create_map_result(layers: List[Dict[str, Any]], title: str = "Map"):
    """Assemble intermediate FeatureCollections into named map layers with a
    union extent. The orchestrator forwards each layer as drawable output."""
    if not isinstance(layers, list) or not layers:
        raise ToolError("'layers' must be a non-empty array of result references")
    named = []
    for i, layer in enumerate(layers):
        feats = features_of(layer, f"layers[{i}]")
        named.append({"title": (layer.get("dataset") or f"layer_{i}"),
                      "features": feats,
                      "count": len(feats)})
    xs, ys = [], []
    for layer in named:
        for f in layer["features"]:
            for x, y in _positions(((f.get("geometry") or {}).get("coordinates")) or []):
                xs.append(x)
                ys.append(y)
    extent = [min(xs), min(ys), max(xs), max(ys)] if xs else None
    return {"ok": True, "type": "map_layers", "title": title,
            "layers": named, "extent": extent}


def _positions(coords):
    if not coords:
        return
    if isinstance(coords[0], (int, float)):
        yield coords[0], coords[1]
    else:
        for part in coords:
            yield from _positions(part)


def style_layer(input: Dict[str, Any], fill_color: str = "",
                color: str = "", weight: float | None = None,
                opacity: float | None = None, radius: float | None = None):
    """Attach a frontend style override (hex colours, stroke weight, point
    radius) to a FeatureCollection. Empty strings leave values unset."""
    import re

    feats = features_of(input)
    style: Dict[str, Any] = {}
    for key, value in (("fillColor", fill_color), ("color", color)):
        if value:
            if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value):
                raise ToolError(f"'{key}' must be a hex colour like '#d03b3b'")
            style[key] = value
    if weight is not None:
        style["weight"] = float(weight)
    if opacity is not None:
        if not 0 <= float(opacity) <= 1:
            raise ToolError("opacity must be within 0..1")
        style["opacity"] = float(opacity)
    if radius is not None:
        if float(radius) <= 0:
            raise ToolError("radius must be positive")
        style["radius"] = float(radius)
    out = collection([dict(f) for f in feats], style_applied=bool(style))
    out["style"] = style
    if input.get("dataset"):
        out["dataset"] = input["dataset"]
    return out


def export_geojson(input: Dict[str, Any], filename: str = "layer.geojson"):
    """Serialise a FeatureCollection to a download payload."""
    feats = features_of(input)
    name = _safe_filename(filename, ".geojson")
    return {"ok": True, "type": "download", "filename": name,
            "mime": "application/geo+json", "count": len(feats),
            "content": json.dumps({"type": "FeatureCollection",
                                   "features": feats})}


def export_csv(input: Dict[str, Any], filename: str = "table.csv"):
    """Serialise a table (or feature properties) to a CSV download payload."""
    if input.get("type") == "table":
        columns = input.get("columns", [])
        rows = input.get("rows", [])
    else:
        feats = features_of(input)
        columns = sorted({k for f in feats for k in (f.get("properties", {}) or {})})
        rows = [f.get("properties", {}) or {} for f in feats]
    lines = [_csv_row(columns)]
    for r in rows:
        lines.append(_csv_row([r.get(c) for c in columns]))
    name = _safe_filename(filename, ".csv")
    return {"ok": True, "type": "download", "filename": name,
            "mime": "text/csv", "count": len(rows),
            "content": "\n".join(lines)}


def _csv_row(values: List[Any]) -> str:
    cells = []
    for v in values:
        text = "" if v is None else str(v)
        cells.append(f'"{text}"' if any(c in text for c in (',', '"', "\n"))
                     else text)
    return ",".join(c.replace('"', '""') if c.startswith('"') else c
                    for c in cells)


def _safe_filename(filename: str, suffix: str) -> str:
    import re

    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(filename or "")).strip("._") or "download"
    return name if name.endswith(suffix) else name + suffix


def create_choropleth(input: Dict[str, Any], attribute: str, classes: int = 5,
                      scheme: str = "quantiles"):
    """Attach a graduated-colour spec (quantile or equal-interval breaks) to
    a layer for frontend ramp rendering."""
    import numpy as np

    from ..common import cap_int

    classes = cap_int(classes, 2, 9, name="classes")
    if scheme not in ("quantiles", "equal_interval"):
        raise ToolError("scheme must be quantiles|equal_interval")
    feats = features_of(input)
    vals = sorted(float((f.get("properties", {}) or {})[attribute])
                  for f in feats
                  if isinstance((f.get("properties", {}) or {}).get(attribute),
                                (int, float))
                  and not isinstance((f.get("properties", {}) or {}).get(attribute), bool))
    if len(vals) < classes:
        raise ToolError(f"need at least {classes} numeric values for "
                        f"'{attribute}'")
    arr = np.asarray(vals)
    if scheme == "quantiles":
        breaks = [float(np.quantile(arr, i / classes)) for i in range(1, classes)]
    else:
        breaks = [float(arr.min() + (arr.max() - arr.min()) * i / classes)
                  for i in range(1, classes)]
    breaks = sorted(set(round(b, 4) for b in breaks))
    while len(breaks) < classes - 1:
        breaks.append(round(float(arr.max()), 4))
    out = collection([dict(f) for f in feats])
    out["choropleth"] = {"attribute": attribute, "breaks": breaks,
                         "min": float(arr.min()), "max": float(arr.max()),
                         "legendTitle": f"{attribute} ({scheme})"}
    if input.get("dataset"):
        out["dataset"] = input["dataset"]
    return out


MAPS_SCHEMAS = {
    "create_map_result": ({"properties": {
        "layers": {"description": "Array of result references, e.g. [\"$a\", \"$b\"]."},
        "title": {"type": "string"}}}, ["layers"]),
    "style_layer": ({"properties": {
        "input": {"description": "Result reference."},
        "fill_color": {"type": "string", "description": "Hex, e.g. '#d03b3b'."},
        "color": {"type": "string", "description": "Hex stroke."},
        "weight": {"type": "number"}, "opacity": {"type": "number"},
        "radius": {"type": "number", "description": "Point radius."}}}, ["input"]),
    "export_geojson": ({"properties": {
        "input": {"description": "Result reference."},
        "filename": {"type": "string"}}}, ["input"]),
    "export_csv": ({"properties": {
        "input": {"description": "Result reference (table or features)."},
        "filename": {"type": "string"}}}, ["input"]),
    "create_choropleth": ({"properties": {
        "input": {"description": "Result reference."},
        "attribute": {"type": "string", "description": "Numeric field."},
        "classes": {"type": "integer", "description": "2..9 (default 5)."},
        "scheme": {"type": "string", "description": "quantiles|equal_interval."}}},
        ["input", "attribute"]),
}
