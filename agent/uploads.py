"""User-uploaded datasets: storage, ingest, registry file.

Uploads live under ``data/uploads/`` with a sidecar ``registry.json`` that
describes each dataset. Supported types:

* CSV — point layer when latitude/longitude-like columns exist, else table.
* GeoJSON (.geojson/.json) — FeatureCollection (single Features wrapped).
* XLSX (.xlsx/.xls) — first sheet; point layer if lat/lon columns exist.

Coordinates are assumed EPSG:4326 (documented on every entry as
``crs_assumed``). Caps: 25 MB files, 5,000 features/rows indexed per dataset
(the registry records totals; queries page within the cap).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any, Dict, List, Optional

UPLOAD_DIR = "data/uploads"
REGISTRY_FILE = os.path.join(UPLOAD_DIR, "registry.json")
MAX_BYTES = 25 * 1024 * 1024
MAX_FEATURES = 5000

LAT_NAMES = {"lat", "latitude", "y", "y_coord", "lat_dd"}
LON_NAMES = {"lon", "lng", "long", "longitude", "x", "x_coord", "lon_dd", "long_dd"}


def _slug(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename))[0]
    slug = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_") or "dataset"
    return slug[:48]


def _load_registry() -> List[Dict[str, Any]]:
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return []


def _save_registry(entries: List[Dict[str, Any]]) -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(REGISTRY_FILE, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)


def list_uploads() -> List[Dict[str, Any]]:
    return _load_registry()


def delete_upload(name: str) -> Dict[str, Any]:
    entries = _load_registry()
    keep = [e for e in entries if e.get("name") != name]
    if len(keep) == len(entries):
        return {"ok": False, "error": f"unknown uploaded dataset '{name}'"}
    gone = [e for e in entries if e.get("name") == name][0]
    try:
        for key in ("path", "source_file"):
            if gone.get(key) and os.path.exists(gone[key]):
                os.remove(gone[key])
    except OSError as exc:
        return {"ok": False, "error": f"could not remove file: {exc}"}
    _save_registry(keep)
    return {"ok": True, "deleted": name}


def _unique_name(slug: str) -> str:
    taken = {e.get("name") for e in _load_registry()}
    if slug not in taken:
        return slug
    i = 2
    while f"{slug}_{i}" in taken:
        i += 1
    return f"{slug}_{i}"


def _detect_latlon(columns) -> Optional[tuple]:
    lower = {str(c).strip().lower(): c for c in columns}
    lat = next((lower[k] for k in LAT_NAMES if k in lower), None)
    lon = next((lower[k] for k in LON_NAMES if k in lower), None)
    if lat is None or lon is None:
        return None
    return lat, lon


def ingest_upload(filename: str, data: bytes) -> Dict[str, Any]:
    """Validate + store an uploaded file; returns the registry entry."""
    if len(data) > MAX_BYTES:
        return {"ok": False, "error": f"file exceeds {MAX_BYTES // 1024 // 1024} MB cap"}
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".csv", ".geojson", ".json", ".xlsx", ".xls"):
        return {"ok": False,
                "error": f"unsupported type '{ext}'; use CSV, GeoJSON, or XLSX"}
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = _unique_name(_slug(filename))
    path = os.path.join(UPLOAD_DIR, f"{name}{ext}")
    with open(path, "wb") as fh:
        fh.write(data)
    try:
        if ext in (".geojson", ".json"):
            entry = _ingest_geojson(name, filename, path)
        elif ext == ".csv":
            entry = _ingest_tabular(name, filename, path, "csv")
        else:
            entry = _ingest_tabular(name, filename, path, "xlsx")
    except Exception as exc:
        if os.path.exists(path):
            os.remove(path)
        return {"ok": False, "error": f"could not parse file: {exc}"}
    entries = _load_registry()
    entries.append(entry)
    _save_registry(entries)
    return {"ok": True, "dataset": entry}


def _ingest_geojson(name: str, filename: str, path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if isinstance(doc, dict) and doc.get("type") == "Feature":
        doc = {"type": "FeatureCollection", "features": [doc]}
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection" \
            or not isinstance(doc.get("features"), list):
        raise ValueError("not a GeoJSON FeatureCollection")
    feats = doc["features"]
    kinds = {str(f.get("geometry", {}).get("type", "")).lower() for f in feats if f.get("geometry")}
    kind = "points" if kinds and all("point" in k for k in kinds) else "geometries"
    fields: List[str] = []
    for f in feats[:20]:
        for k in (f.get("properties") or {}):
            if k not in fields:
                fields.append(str(k))
    return _entry(name, filename, path, kind, fields, len(feats))


def _ingest_tabular(name: str, filename: str, path: str, fmt: str) -> Dict[str, Any]:
    import pandas as pd

    if fmt == "csv":
        df = pd.read_csv(path, nrows=MAX_FEATURES + 1)
    else:
        df = pd.read_excel(path, nrows=MAX_FEATURES + 1)
    total = len(df)
    df = df.head(MAX_FEATURES)
    latlon = _detect_latlon(df.columns)
    if not latlon:
        return _entry(name, filename, path, "table",
                      [str(c) for c in df.columns], total)
    # Materialise points as GeoJSON so the query path reads one format.
    lat_col, lon_col = latlon
    features = []
    for _, row in df.iterrows():
        try:
            lon, lat = float(row[lon_col]), float(row[lat_col])
        except (TypeError, ValueError):
            continue
        props = {str(k): (None if pd.isna(v) else v) for k, v in row.items()}
        for k, v in list(props.items()):
            if hasattr(v, "isoformat"):
                try:
                    props[k] = str(v)
                except Exception:
                    props[k] = None
        features.append({"type": "Feature", "properties": props,
                         "geometry": {"type": "Point", "coordinates": [lon, lat]}})
    geo_path = os.path.splitext(path)[0] + ".geojson"
    with open(geo_path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh)
    entry = _entry(name, filename, geo_path, "points",
                   [str(c) for c in df.columns], total, latlon=list(latlon))
    entry["source_file"] = path
    return entry


def _entry(name, filename, path, kind, fields, count, latlon=None):
    entry: Dict[str, Any] = {
        "name": name,
        "original_filename": filename,
        "path": path,
        "kind": kind,  # points | geometries | table
        "crs": "EPSG:4326",
        "crs_assumed": kind != "table",
        "fields": fields,
        "count": int(count),
        "capped": bool(count and count >= MAX_FEATURES),
        "uploaded_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    if latlon:
        entry["latlon_columns"] = latlon
    return entry
