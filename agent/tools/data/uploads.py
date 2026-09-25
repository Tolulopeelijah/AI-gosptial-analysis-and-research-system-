"""Controlled query interface for user-uploaded datasets.

Spatial uploads (points/geometries) return GeoJSON FeatureCollections with
optional bbox filtering; tabular uploads return capped tables. Coordinates
are served as stored (assumed EPSG:4326 at ingest; see agent/uploads.py).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

MAX_FEATURES = 1000


def _get_entry(dataset: str) -> Dict[str, Any]:
    from ...uploads import list_uploads

    for e in list_uploads():
        if e.get("name") == dataset:
            return e
    raise ValueError(
        f"unknown uploaded dataset '{dataset}'. "
        "Upload a file first, or pick a registered dataset.")


def _bbox_filter(features: List[Dict[str, Any]], bbox: str) -> List[Dict[str, Any]]:
    try:
        west, south, east, north = [float(x) for x in bbox.split(",")]
    except ValueError:
        raise ValueError(f"invalid bbox '{bbox}'")
    kept = []
    for f in features:
        g = (f.get("geometry") or {})
        coords = g.get("coordinates")
        if coords is None:
            continue
        pts = coords if g.get("type") == "Point" else None
        if pts is None:  # polygons/rings: flatten one level for the test
            try:
                ring = coords[0] if isinstance(coords[0][0], (list, tuple)) else coords
                xs = [c[0] for c in ring]
                ys = [c[1] for c in ring]
            except (IndexError, TypeError):
                continue
        else:
            xs, ys = [pts[0]], [pts[1]]
        if max(xs) >= west and min(xs) <= east and max(ys) >= south and min(ys) <= north:
            kept.append(f)
    return kept


def query_user_dataset(
    dataset: str,
    max_features: int = 500,
    bbox: Optional[str] = None,
) -> Dict[str, Any]:
    """Query one uploaded dataset by its registered name."""
    try:
        entry = _get_entry(dataset)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "data_unavailable"}
    max_features = max(1, min(int(max_features), MAX_FEATURES))
    kind = entry.get("kind", "table")

    if kind in ("points", "geometries"):
        with open(entry["path"], encoding="utf-8") as fh:
            doc = json.load(fh)
        feats = doc.get("features", [])
        if bbox:
            try:
                feats = _bbox_filter(feats, bbox)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        feats = feats[:max_features]
        return {
            "ok": True,
            "type": "FeatureCollection",
            "features": feats,
            "count": len(feats),
            "dataset": dataset,
            "geometry_type": "user upload",
            "crs": "EPSG:4326 (assumed at ingest)",
            "sources": [{"dataset": dataset,
                         "file": entry.get("original_filename")}],
        }

    # Tabular uploads (CSV/XLSX without coordinates).
    import pandas as pd

    path = entry["path"]
    df = (pd.read_csv(path) if path.endswith(".csv")
          else pd.read_excel(path)).head(max_features)
    rows = df.to_dict(orient="records")
    clean = [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in rows]
    for r in clean:
        for k, v in list(r.items()):
            if hasattr(v, "isoformat"):
                try:
                    r[k] = str(v)
                except Exception:
                    r[k] = None
    return {
        "ok": True,
        "type": "table",
        "dataset": dataset,
        "columns": [str(c) for c in df.columns],
        "rows": clean,
        "row_count": entry.get("count", len(clean)),
        "returned": len(clean),
    }


QUERY_USER_DATASET_SCHEMA = {
    "properties": {
        "dataset": {
            "type": "string",
            "description": (
                "Registered name of an uploaded dataset (see list_datasets). "
                "Use for questions about user-provided files."
            ),
        },
        "max_features": {
            "type": "integer",
            "description": "Max features/rows returned (default 500, cap 1000).",
        },
        "bbox": {
            "type": "string",
            "description": "Optional 'west,south,east,north' (EPSG:4326) spatial filter.",
        },
    }
}
QUERY_USER_DATASET_REQUIRED = ["dataset"]
