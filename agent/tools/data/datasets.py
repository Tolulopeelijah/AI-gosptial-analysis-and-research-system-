"""Dataset discovery and generic data access.

Semantic-first: `search_datasets` / `get_dataset_schema` / `get_dataset_extent`
/ `get_dataset_extent` work from registry names, keeping raw URLs out of
plans. `filter_features` / `sample_features` operate on result references.
`download_dataset` pages a full layer into the store. `query_wfs` is a real
WFS GetFeature client; `wms_getmap` validates against GetCapabilities and
returns a display-ready GetMap URL (map images are for viewing, not analysis).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..common import (CapabilityError, ToolError, cap_int, collection,
                      features_of, http_get, parse_bbox, table)


def search_datasets(query: str):
    """Keyword search over registered datasets (name/description/fields)."""
    from ...registry import build_registry

    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", query or "") if len(t) > 1]
    if not terms:
        raise ToolError("provide a search query")
    hits = []
    for name, info in build_registry().items():
        hay = f"{name} {info.description} {' '.join(info.fields)}".lower()
        score = sum(hay.count(t) for t in terms)
        if score:
            hits.append({"dataset": name, "score": score,
                         "available": info.available,
                         "access_method": info.access_method,
                         "description": info.description[:200]})
    hits.sort(key=lambda h: -h["score"])
    return {"ok": True, "query": query, "hits": hits, "count": len(hits)}


def get_dataset_schema(dataset: str):
    """Field list for a dataset (live ArcGIS discovery where reachable)."""
    from ...registry import build_registry
    from .arcgis import _layer_urls, describe_layer

    reg = build_registry()
    if dataset not in reg:
        raise ToolError(f"unknown dataset '{dataset}'")
    info = reg[dataset]
    if info.source_type == "arcgis_feature_server":
        from ...config import settings

        if settings.ARCGIS_USE_MOCK:
            from .arcgis_mock import describe_mock

            meta = describe_mock(dataset)
            return {"ok": True, "dataset": dataset,
                    "fields": meta.get("fields", []),
                    "geometry_type": meta.get("geometryType"),
                    "mocked": True, "provisional_schema": True}
        fields: List[Dict[str, Any]] = []
        for url in _layer_urls(dataset, info.extra):
            meta = describe_layer(url)
            fields.extend(meta.get("fields", []))
        return {"ok": True, "dataset": dataset, "fields": fields}
    return {"ok": True, "dataset": dataset,
            "fields": [{"name": f} for f in info.fields]}


def get_dataset_extent(dataset: str):
    """Spatial (and, for Maumee, temporal) extent of a dataset."""
    from ...registry import build_registry

    reg = build_registry()
    if dataset not in reg:
        raise ToolError(f"unknown dataset '{dataset}'")
    info = reg[dataset]
    if info.source_type == "local_xlsx":
        from .xlsx import query_maumee

        schema = query_maumee(operation="schema")
        return {"ok": True, "dataset": dataset, "spatial": None,
                "temporal": schema.get("date_range"),
                "note": "station time-series: temporal extent only"}
    if info.source_type == "user_upload":
        from .uploads import query_user_dataset

        res = query_user_dataset(dataset, max_features=5000)
        if res.get("type") == "FeatureCollection":
            return {"ok": True, "dataset": dataset,
                    "spatial": _bbox_of(res["features"]), "temporal": None}
        return {"ok": True, "dataset": dataset, "spatial": None,
                "temporal": None, "note": "tabular upload: no extent"}
    # ArcGIS: mock fixtures or live fullExtent.
    from ...config import settings

    if settings.ARCGIS_USE_MOCK:
        from .arcgis import query_arcgis

        res = query_arcgis(dataset, max_features=2000)
        if not res.get("ok"):
            return res
        return {"ok": True, "dataset": dataset,
                "spatial": _bbox_of(res.get("features", [])),
                "mocked": True, "provisional_schema": True}
    from .arcgis import _layer_urls, describe_layer

    boxes = []
    for url in _layer_urls(dataset, info.extra):
        meta = describe_layer(url)
        boxes.append(meta)
    return {"ok": True, "dataset": dataset, "layers": boxes}


def _bbox_of(features: List[Dict[str, Any]]) -> Optional[List[float]]:
    def positions(coords):
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            yield coords[0], coords[1]
        else:
            for part in coords:
                yield from positions(part)

    xs, ys = [], []
    for f in features:
        for x, y in positions(((f.get("geometry") or {}).get("coordinates")) or []):
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def filter_features(input: Dict[str, Any], where: str):
    """Attribute filter on a result reference. Supports =, !=, >, >=, <, <=
    on numbers/strings and LIKE '%x%' substring, combined with AND."""
    feats = features_of(input)
    clauses = _parse_where(where)
    out = [f for f in feats if all(_match(f.get("properties", {}) or {}, c)
                                   for c in clauses)]
    return collection(out, where=where, matched=len(out), scanned=len(feats))


def _parse_where(where: str) -> List[Dict[str, Any]]:
    parts = re.split(r"\s+AND\s+", (where or "").strip(), flags=re.I)
    clauses = []
    for part in parts:
        m = re.match(r"^\s*([\w.]+)\s*(=|!=|>=|<=|>|<|LIKE)\s*(.+?)\s*$",
                     part, flags=re.I)
        if not m:
            raise ToolError(f"cannot parse condition '{part}'; use "
                            "FIELD = value, FIELD > value, FIELD LIKE '%x%', joined by AND")
        field, op, raw = m.group(1), m.group(2).upper(), m.group(3).strip()
        if (raw.startswith("'") and raw.endswith("'")) or \
           (raw.startswith('"') and raw.endswith('"')):
            value: Any = raw[1:-1]
        else:
            try:
                value = float(raw)
            except ValueError:
                value = raw.strip("'\"")
        if op == "LIKE" and not isinstance(value, str):
            raise ToolError("LIKE needs a string pattern with % wildcards")
        clauses.append({"field": field, "op": op, "value": value})
    if not clauses:
        raise ToolError("empty filter")
    return clauses


def _match(props: Dict[str, Any], clause: Dict[str, Any]) -> bool:
    actual = props.get(clause["field"])
    op, want = clause["op"], clause["value"]
    if op == "LIKE":
        pattern = "^" + re.escape(str(want)).replace("%", ".*") + "$"
        return re.match(pattern, str(actual or ""), flags=re.I) is not None
    try:
        a = float(actual) if isinstance(want, float) else actual
    except (TypeError, ValueError):
        a = actual
    if a is None:
        return False
    if op == "=":
        return a == want
    if op == "!=":
        return a != want
    try:
        if op == ">":
            return a > want
        if op == ">=":
            return a >= want
        if op == "<":
            return a < want
        if op == "<=":
            return a <= want
    except TypeError:
        return False
    return False


def sample_features(input: Dict[str, Any], n: int = 10, seed: int = 42):
    """Deterministic random sample of features (seeded)."""
    import random

    feats = features_of(input)
    n = cap_int(n, 10, 2000, name="n")
    rng = random.Random(seed)
    picked = rng.sample(feats, min(n, len(feats))) if feats else []
    return collection(picked, sampled=len(picked), scanned=len(feats), seed=seed)


def download_dataset(dataset: str, max_features: int = 5000,
                     bbox: Optional[str] = None):
    """Page a whole layer into one FeatureCollection (capped, flagged)."""
    from ...registry import build_registry

    reg = build_registry()
    if dataset not in reg:
        raise ToolError(f"unknown dataset '{dataset}'")
    info = reg[dataset]
    if info.source_type != "arcgis_feature_server":
        raise ToolError(f"download_dataset is for ArcGIS layers; '{dataset}' uses "
                        f"{info.access_method}")
    from ...config import settings

    if settings.ARCGIS_USE_MOCK:
        from .arcgis import query_arcgis

        res = query_arcgis(dataset, max_features=min(max_features, 2000),
                           bbox=bbox)
        res["download"] = True
        return res
    from .arcgis import _layer_urls

    import requests

    max_features = cap_int(max_features, 1000, 5000, name="max_features")
    params: Dict[str, Any] = {"where": "1=1", "outFields": "*",
                              "returnGeometry": "true", "f": "geojson",
                              "resultRecordCount": 1000}
    if bbox:
        w, s, e, n = parse_bbox(bbox)
        params.update({"geometry": f"{w},{s},{e},{n}",
                       "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                       "spatialRel": "esriSpatialRelIntersects"})
    feats: List[Dict[str, Any]] = []
    truncated = False
    for url in _layer_urls(dataset, info.extra):
        offset = 0
        while len(feats) < max_features:
            try:
                resp = requests.get(url.rstrip("/") + "/query",
                                    params={**params, "resultOffset": offset},
                                    timeout=60)
                resp.raise_for_status()
                page = resp.json()
            except Exception as exc:
                raise CapabilityError(f"download from {url} failed: {exc}") from exc
            if "error" in page:
                raise CapabilityError(f"server error: {page['error']}")
            batch = page.get("features", [])
            if not batch:
                break
            feats.extend(batch)
            if not page.get("exceededTransferLimit"):
                break
            offset += len(batch)
        if len(feats) >= max_features:
            truncated = True
            break
    feats = feats[:max_features]
    out = collection(feats, download=True, truncated=truncated)
    out["dataset"] = dataset
    return out


def query_wfs(url: str, typename: str, max_features: int = 1000,
              bbox: Optional[str] = None):
    """WFS GetFeature as GeoJSON (services must support JSON output)."""
    max_features = cap_int(max_features, 100, 5000, name="max_features")
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
              "typeNames": typename, "outputFormat": "application/json",
              "count": max_features, "srsName": "urn:ogc:def:crs:EPSG::4326"}
    if bbox:
        w, s, e, n = parse_bbox(bbox)
        params["bbox"] = f"{s},{w},{n},{e},urn:ogc:def:crs:EPSG::4326"
    resp = http_get(url, params=params, timeout=60)
    try:
        doc = resp.json()
    except Exception as exc:
        raise CapabilityError("WFS response was not JSON; this tool needs "
                              "outputFormat=application/json support") from exc
    feats = doc.get("features", [])[:max_features]
    return collection(feats, service="WFS", typename=typename, url=url)


def wms_getmap(url: str, layers: str, bbox: str, width: int = 800,
               height: int = 600, image_format: str = "image/png"):
    """Validate layers against GetCapabilities, then return a display-ready
    WMS GetMap URL (for viewing in a client, not pixel analysis)."""
    w, s, e, n = parse_bbox(bbox)
    width = cap_int(width, 800, 2048, name="width")
    height = cap_int(height, 800, 2048, name="height")
    if image_format not in ("image/png", "image/jpeg"):
        raise ToolError("image_format must be image/png or image/jpeg")
    warning = ""
    try:
        caps = http_get(url, params={"service": "WMS", "version": "1.3.0",
                                     "request": "GetCapabilities"}, timeout=30).text
        available = set(re.findall(r"<Name>([^<]+)</Name>", caps))
        missing = [lyr for lyr in layers.split(",") if lyr.strip() not in available]
        if missing:
            raise ToolError(f"layers not advertised by service: {missing}")
    except (CapabilityError, ToolError) as exc:
        if isinstance(exc, ToolError) and "not advertised" in str(exc):
            raise
        warning = f"capabilities unchecked ({exc}); URL unvalidated"
    import urllib.parse

    query = urllib.parse.urlencode({
        "service": "WMS", "version": "1.3.0", "request": "GetMap",
        "layers": layers, "styles": "", "crs": "EPSG:4326",
        "bbox": f"{s},{w},{n},{e}", "width": width, "height": height,
        "format": image_format})
    map_url = url.rstrip("/") + ("&" if "?" in url else "?") + query
    return {"ok": True, "map_url": map_url, "layers": layers,
            "bbox": [w, s, e, n], "warning": warning or None}


DATASETS_SCHEMAS = {
    "search_datasets": ({"properties": {
        "query": {"type": "string", "description": "Keywords, e.g. 'flood water quality'."}}},
        ["query"]),
    "get_dataset_schema": ({"properties": {
        "dataset": {"type": "string", "description": "Semantic dataset name."}}},
        ["dataset"]),
    "get_dataset_extent": ({"properties": {
        "dataset": {"type": "string"}}}, ["dataset"]),
    "filter_features": ({"properties": {
        "input": {"description": "Result reference."},
        "where": {"type": "string",
                  "description": "e.g. \"STATUS = 'Active' AND OBJECTID > 3\"."}}},
        ["input", "where"]),
    "sample_features": ({"properties": {
        "input": {"description": "Result reference."},
        "n": {"type": "integer", "description": "Sample size (default 10)."},
        "seed": {"type": "integer", "description": "Deterministic seed (default 42)."}}},
        ["input"]),
    "download_dataset": ({"properties": {
        "dataset": {"type": "string"},
        "max_features": {"type": "integer", "description": "Cap (default 5000)."},
        "bbox": {"type": "string", "description": "Optional spatial filter."}}},
        ["dataset"]),
    "query_wfs": ({"properties": {
        "url": {"type": "string", "description": "WFS endpoint."},
        "typename": {"type": "string", "description": "Feature type name."},
        "max_features": {"type": "integer"},
        "bbox": {"type": "string", "description": "Optional filter."}}},
        ["url", "typename"]),
    "wms_getmap": ({"properties": {
        "url": {"type": "string", "description": "WMS endpoint."},
        "layers": {"type": "string", "description": "Comma-separated layer names."},
        "bbox": {"type": "string"},
        "width": {"type": "integer"}, "height": {"type": "integer"},
        "image_format": {"type": "string"}}},
        ["url", "layers", "bbox"]),
}
