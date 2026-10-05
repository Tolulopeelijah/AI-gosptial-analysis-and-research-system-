"""Controlled ArcGIS FeatureServer query tool.

The model supplies *semantic* parameters (`dataset`, optional attribute /
spatial filters). This module translates them into ArcGIS REST requests.

Pagination model (Part 1):
  * ``page_size`` is the per-request service limit (``resultRecordCount``,
    capped at ``PAGE_SIZE_MAX`` = 2000 — the service page size, not the
    analysis ceiling).
  * ``max_features`` is the caller's total intent for this query (default
    1000, historical default cap 2000 via ``MAX_FEATURES`` for backwards
    compatibility). Explicit larger values page automatically with
    ``resultOffset``/``resultRecordCount`` until ``exceededTransferLimit``
    clears or ``max_features``/``ABSOLUTE_MAX_FEATURES`` is reached.
  * Server-side spatial filtering (``near`` + ``distance_km`` or the
    equivalent high-level ``spatial_filter`` dict) is preferred over
    downloading whole layers: the ArcGIS server performs the
    within-distance predicate and only matching features are transferred.
  * When the service cannot perform distance queries, the tool falls back
    to a *complete* paginated fetch + local metric computation — never a
    silent first-2000 subset. Truncation is always reported explicitly.

Service metadata (geometry type, fields, CRS, capabilities) is discovered at
runtime via `?f=json` — never hardcoded. Datasets without a configured URL
report `available: False` so the agent can honestly say the capability is
missing instead of inventing data.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

TIMEOUT = 30
MAX_FEATURES = 2000  # historical default total cap (kept for backwards compat)
# Default rows per paged request. The county layers advertise
# maxRecordCount=2000, and each round trip costs seconds on that server, so
# page at the service maximum to minimise request count (slow-query budget).
PAGE_SIZE = 2000
PAGE_SIZE_MAX = 2000  # per-request service page size (resultRecordCount ceiling)
ABSOLUTE_MAX_FEATURES = 50000  # hard safety ceiling for explicit full-analysis fetches
MAX_PAGES_GUARD = 100  # infinite-pagination-loop guard (per URL)
MAX_GEOMETRY_CHARS = 8000  # POST-body guard before simplify/batch
NEAR_BATCH_SIZE = 8  # reference polygons per spatial request when batching
MAX_REFERENCE_FEATURES = 5000  # reference geometries above this need explicit bbox/narrowing

# Service capability cache: url -> parsed capability dict.
_CAPABILITY_CACHE: Dict[str, Dict[str, Any]] = {}


def _mock_enabled() -> bool:
    from ...config import settings

    return settings.ARCGIS_USE_MOCK


def _layer_urls(dataset: str, extra: Optional[Dict[str, Any]] = None) -> List[str]:
    from ...config import settings

    extra = extra or {}
    if dataset == "septic_systems":
        return [settings.ARCGIS_SEPTIC_URL] if settings.ARCGIS_SEPTIC_URL else []
    if dataset == "floodplains":
        urls = []
        if settings.ARCGIS_FLOODPLAIN_0_URL:
            urls.append(settings.ARCGIS_FLOODPLAIN_0_URL)
        if settings.ARCGIS_FLOODPLAIN_4_URL:
            urls.append(settings.ARCGIS_FLOODPLAIN_4_URL)
        return urls
    return []


def _decode_json_dict(resp, url: str, via: str) -> Dict[str, Any]:
    """Decode a JSON-object ArcGIS response or raise a diagnostic error.

    The county server occasionally returns HTTP 200 with an empty/null/non-
    object body under load; surfacing that distinctly (instead of a bare
    ``'NoneType' has no attribute 'get'`` deep in paging code) is what makes
    remote diagnosis possible.
    """
    try:
        payload = resp.json()
    except Exception as exc:
        raise RuntimeError(
            f"{via}: non-JSON response (HTTP {resp.status_code}): "
            f"{str(exc)[:120]}") from exc
    if payload is None:
        raise RuntimeError(f"{via}: empty (null) response body")
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{via}: unexpected response type {type(payload).__name__}")
    return payload


def _features_of_page(page: Any, url: str, via: str) -> Tuple[List[Dict[str, Any]], bool]:
    """(dict-only features, exceededTransferLimit) from a decoded payload."""
    if page is None:
        raise RuntimeError(f"{via}: empty (null) response body")
    if not isinstance(page, dict):
        raise RuntimeError(f"{via}: unexpected response type "
                            f"{type(page).__name__}")
    if "error" in page:
        raise RuntimeError(f"{via}: {page['error']}")
    raw = page.get("features", []) or []
    feats = [f for f in raw if isinstance(f, dict)]
    if len(feats) != len(raw):
        log.warning("query_arcgis %s %s: skipped %d non-dict features",
                    url, via, len(raw) - len(feats))
    return feats, bool(page.get("exceededTransferLimit"))


def _decode_feature_page(resp, url: str, via: str) -> Tuple[List[Dict[str, Any]], bool]:
    """(dict-only features, exceededTransferLimit) from a query response."""
    return _features_of_page(_decode_json_dict(resp, url, via), url, via)


def describe_layer(url: str) -> Dict[str, Any]:
    """Fetch live service metadata for one FeatureServer layer."""
    resp = requests.get(url.rstrip("/") + "?f=json", timeout=TIMEOUT)
    resp.raise_for_status()
    meta = _decode_json_dict(resp, url, "metadata")
    fields = [
        {"name": f.get("name"), "type": f.get("type"), "alias": f.get("alias")}
        for f in meta.get("fields", [])
    ]
    sr = meta.get("extent", {}).get("spatialReference", {}) or {}
    return {
        "name": meta.get("name"),
        "geometryType": meta.get("geometryType"),
        "fields": fields,
        "field_names": [f["name"] for f in fields if f.get("name")],
        "spatialReference": sr,
        "capabilities": meta.get("capabilities"),
        "maxRecordCount": meta.get("maxRecordCount"),
        "supportedQueryFormats": meta.get("supportedQueryFormats"),
        **_capability_flags(meta),
    }


def _capability_flags(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Esri capability flags (never assume support)."""
    adv = meta.get("advancedQueryCapabilities") or {}
    return {
        "supportsPagination": bool(
            meta.get("supportsPagination", adv.get("supportsPagination", False))
        ),
        "supportsQueryWithDistance": bool(meta.get("supportsQueryWithDistance", False)),
        "supportsAdvancedQueries": bool(meta.get("supportsAdvancedQueries", False)),
        "supportsStatistics": bool(adv.get("supportsStatistics", False)),
    }


def get_layer_capabilities(url: str) -> Dict[str, Any]:
    """Best-effort capability probe for one layer URL (cached).

    Returns ``{"supportsPagination": ..., "supportsQueryWithDistance": ...,
    "supportsAdvancedQueries": ..., "maxRecordCount": ..., "error": ...}``.
    Network/metadata failures yield ``{"unknown": True}`` so callers apply
    the safe default (assume pagination works via resultOffset, verify
    distance support by probing, never assume).
    """
    if url in _CAPABILITY_CACHE:
        return _CAPABILITY_CACHE[url]
    try:
        meta = describe_layer(url)
        # A minimal stub (e.g. {"geometryType": ...} in tests) carries no
        # capability keys — treat as inconclusive, not as explicit False,
        # so paging is still attempted with repeat-page detection as guard.
        has_keys = any(k in meta for k in (
            "supportsPagination", "supportsQueryWithDistance",
            "supportsAdvancedQueries", "advancedQueryCapabilities",
            "capabilities", "maxRecordCount"))
        if not has_keys and "features" in meta:
            caps = {"unknown": True, "error": "non-metadata response"}
        elif not has_keys:
            caps = {"unknown": True, "geometryType": meta.get("geometryType")}
        else:
            caps = {
                "supportsPagination": bool(meta.get("supportsPagination", False)),
                "supportsQueryWithDistance": bool(meta.get("supportsQueryWithDistance", False)),
                "supportsAdvancedQueries": bool(meta.get("supportsAdvancedQueries", False)),
                "maxRecordCount": meta.get("maxRecordCount"),
                "geometryType": meta.get("geometryType"),
            }
    except Exception as exc:
        caps = {"unknown": True, "error": str(exc)[:200]}
    _CAPABILITY_CACHE[url] = caps
    return caps


def clear_capability_cache() -> None:
    """Test hook: reset the capability cache."""
    _CAPABILITY_CACHE.clear()


def _xy(pair):
    return [float(pair[0]), float(pair[1])]


def _esri_rings(polys) -> List:
    rings = []
    for poly in polys:
        rings.append([_xy(c) for c in poly.exterior.coords])
        for hole in poly.interiors:
            rings.append([_xy(c) for c in hole.coords])
    return rings


def _esri_chunk(pairs) -> Tuple[str, str]:
    """One chunk of (feature, EPSG:4326 shapely geom) pairs -> Esri geometry."""
    polys, paths, points = [], [], []
    for _, geom in pairs:
        kind = geom.geom_type
        if kind == "Polygon":
            polys.append(geom)
        elif kind == "MultiPolygon":
            polys.extend(geom.geoms)
        elif kind == "LineString":
            paths.append([_xy(c) for c in geom.coords])
        elif kind == "MultiLineString":
            paths.extend([_xy(c) for c in part.coords] for part in geom.geoms)
        elif kind == "Point":
            points.append(_xy(geom.coords[0]))
        elif kind == "MultiPoint":
            points.extend(_xy(c) for c in geom.coords)
    if polys:
        return json.dumps({"rings": _esri_rings(polys)}), "esriGeometryPolygon"
    if paths:
        return json.dumps({"paths": paths}), "esriGeometryPolyline"
    if points:
        if len(points) == 1:
            return json.dumps({"x": points[0][0], "y": points[0][1]}), \
                "esriGeometryPoint"
        return json.dumps({"points": points}), "esriGeometryMultipoint"
    raise ValueError("near area has no usable geometries")


def _simplify_pairs(pairs, tolerance_m: float):
    """Douglas-Peucker simplification in a metric CRS (for oversized POSTs)."""
    from ..common import metric_crs_for, reproject

    geoms = [g for _, g in pairs]
    metric = metric_crs_for(geoms)
    out = []
    for feat, geom in pairs:
        gm = reproject(geom, "EPSG:4326", metric)
        simple = gm.simplify(tolerance_m, preserve_topology=True)
        if simple.is_empty:
            continue
        out.append((feat, reproject(simple, metric, "EPSG:4326")))
    return out


def _near_chunks(near, distance_m: Optional[float]) -> Tuple[List[Tuple[str, str]], int]:
    """Resolved near FeatureCollection -> Esri POST chunks + feature count."""
    from ..common import crs_of, reproject, valid_shapes

    pairs = [(f, g) for f, g in valid_shapes(near, "near") if not g.is_empty]
    src = crs_of(near)
    if src != "EPSG:4326":
        pairs = [(f, reproject(g, src, "EPSG:4326")) for f, g in pairs]
    if not pairs:
        return [], 0
    chunks = [pairs[i:i + NEAR_BATCH_SIZE]
              for i in range(0, len(pairs), NEAR_BATCH_SIZE)]
    if len(chunks) == 1:
        geom, kind = _esri_chunk(chunks[0])
        if len(geom) <= MAX_GEOMETRY_CHARS:
            return [(geom, kind)], len(pairs)
        tolerance = 100.0 if not distance_m else min(250.0, max(25.0, distance_m / 20.0))
        simple = _simplify_pairs(chunks[0], tolerance)
        if simple:
            geom, kind = _esri_chunk(simple)
            if len(geom) <= MAX_GEOMETRY_CHARS:
                log.info("near geometry simplified (tol %.0f m) for POST", tolerance)
                return [(geom, kind)], len(pairs)
            # Still oversized: keep the simplified pairs for batching below
            # instead of resending the heavier original geometry.
            chunks = [simple[i:i + NEAR_BATCH_SIZE]
                      for i in range(0, len(simple), NEAR_BATCH_SIZE)]
    log.info("near area split into %d POST batches", len(chunks))
    batched = []
    for chunk in chunks:
        geom, kind = _esri_chunk(chunk)
        batched.append((geom, kind))
    return batched, len(pairs)


def _dedupe_key(feature: Any) -> Tuple:
    if not isinstance(feature, dict):
        return ("bad", id(feature))
    props = feature.get("properties", {}) or {}
    oid = props.get("OBJECTID") if isinstance(props, dict) else None
    if oid is not None:
        return ("oid", oid)
    geom = feature.get("geometry")
    return ("geom", json.dumps(geom, sort_keys=True) if geom else id(feature))


def _post_query(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    resp = requests.post(url.rstrip("/") + "/query", data=params, timeout=TIMEOUT)
    resp.raise_for_status()
    page = _decode_json_dict(resp, url, "spatial POST")
    if "error" in page:
        raise RuntimeError(page["error"])
    return page


def _fetch_spatial_pages(
    url: str,
    core: Dict[str, Any],
    chunks,
    max_features: int,
    page_size: int,
    *,
    pagination_supported: bool = True,
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """POST spatial chunks with paging; returns (features, pages, page_info).

    Semantics are OR across chunks: a target matching ANY reference chunk is
    kept (deduped by OBJECTID/geometry). Guards: per-chunk page budget
    (``MAX_PAGES_GUARD``), empty-page break, and repeated-offset detection
    (same ``resultOffset`` yielding zero new features twice stops paging for
    that chunk instead of looping forever).
    """
    collected: List[Dict[str, Any]] = []
    seen = set()
    pages = 0
    stopped_early: Optional[str] = None
    for geometry, geometry_type in chunks:
        params = dict(core, geometry=geometry, geometryType=geometry_type,
                      inSR=4326, spatialRel="esriSpatialRelIntersects")
        chunk_offset = 0
        chunk_pages = 0
        empty_streak = 0
        stepped_down = False
        last_new_total = len(collected)
        while len(collected) < max_features:
            if chunk_pages >= MAX_PAGES_GUARD:
                stopped_early = f"page guard ({MAX_PAGES_GUARD}/chunk)"
                break
            req = dict(params, f="geojson",
                       resultRecordCount=min(page_size, max_features - len(collected)))
            if chunk_offset and pagination_supported:
                req["resultOffset"] = chunk_offset
            page = _post_query(url, req)
            feats, exceeded = _features_of_page(page, url, "spatial page")
            new = 0
            for feat in feats:
                key = _dedupe_key(feat)
                if key not in seen:
                    seen.add(key)
                    collected.append(feat)
                    new += 1
            pages += 1
            chunk_pages += 1
            if not feats:
                if (chunk_pages == 1 and chunk_offset == 0
                        and not stepped_down and page_size > 100):
                    # First page inexplicably empty: the county server
                    # sometimes blanks on large record counts. Retry the same
                    # offset once with a smaller page before concluding zero.
                    page_size = max(100, page_size // 4)
                    stepped_down = True
                    log.info("query_arcgis %s: empty first page, stepping "
                             "down to page_size=%d", url, page_size)
                    continue
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
            if len(collected) == last_new_total and feats:
                # Server ignored resultOffset (returned the same page):
                # count it once, then stop this chunk to avoid an infinite loop.
                if chunk_pages > 1:
                    stopped_early = "server ignored resultOffset (repeat page)"
                    break
            last_new_total = len(collected)
            if not exceeded or not feats:
                break
            if not pagination_supported:
                stopped_early = "pagination unsupported (single page)"
                break
            chunk_offset += len(feats)
        if len(collected) >= max_features:
            break
    info = {"stopped_early": stopped_early} if stopped_early else {}
    return collected, pages, info


SPATIAL_FILTER_RELATIONSHIPS = ("within_distance", "intersects")

_DISTANCE_TO_M = {
    "meters": 1.0, "metres": 1.0, "m": 1.0,
    "kilometers": 1000.0, "kilometres": 1000.0, "km": 1000.0,
    "feet": 0.3048, "foot": 0.3048, "ft": 0.3048,
    "miles": 1609.344, "mile": 1609.344, "mi": 1609.344,
}


def _resolve_spatial_args(
    near: Any,
    distance_km: Optional[float],
    spatial_filter: Optional[Dict[str, Any]],
) -> Tuple[Any, Optional[float], Optional[Dict[str, Any]]]:
    """Normalise ``near``/``distance_km`` and high-level ``spatial_filter``.

    ``spatial_filter`` is the LLM-friendly form that never exposes raw Esri
    REST params::

        {"reference": "$floodplains" | FeatureCollection | "floodplains",
         "relationship": "within_distance" | "intersects",
         "distance": 2000, "units": "meters"}

    ``reference`` as a dataset name is resolved by the caller (paginated
    fetch); here it is passed through so ``query_arcgis`` can fetch it.
    Returns ``(near_fc_or_name, distance_km, echo)``.
    """
    if spatial_filter is None:
        return near, distance_km, None
    if not isinstance(spatial_filter, dict):
        raise ValueError("spatial_filter must be an object")
    ref = spatial_filter.get("reference", spatial_filter.get("reference_dataset"))
    rel = (spatial_filter.get("relationship") or "within_distance").lower()
    if rel not in SPATIAL_FILTER_RELATIONSHIPS:
        raise ValueError(
            f"unknown spatial relationship '{rel}'; use one of "
            f"{', '.join(SPATIAL_FILTER_RELATIONSHIPS)}"
        )
    dist = spatial_filter.get("distance")
    units = (spatial_filter.get("units") or "meters").lower()
    dist_km: Optional[float] = None
    if rel == "within_distance":
        if dist is None:
            raise ValueError("spatial_filter within_distance needs 'distance'")
        try:
            factor = _DISTANCE_TO_M[units]
        except KeyError:
            raise ValueError(f"unknown units '{units}'; use meters|kilometers|feet|miles")
        dist_km = float(dist) * factor / 1000.0
        if dist_km <= 0:
            raise ValueError("spatial_filter distance must be positive")
    # Explicit near/distance_km args win when both forms are given.
    echo = {
        "relationship": rel,
        "distance": dist,
        "units": units,
        "reference": (
            ref if isinstance(ref, str)
            else f"FeatureCollection({len((ref or {}).get('features', []))})"
            if isinstance(ref, dict) else None
        ),
    }
    return (near if near is not None else ref), (
        distance_km if distance_km is not None else dist_km), echo


def _local_within_distance_fallback(
    target_features: List[Dict[str, Any]],
    reference_fc: Dict[str, Any],
    distance_m: Optional[float],
) -> List[Dict[str, Any]]:
    """Client-side ANY-semantics filter in a local metric CRS.

    Keeps target features within ``distance_m`` of the union of reference
    geometries (or intersecting the union when ``distance_m`` is None).
    Metric work reprojects to UTM/AEQD — never naive degrees. Invalid
    geometries are skipped and counted by the caller via lengths.
    """
    from ..common import crs_of, metric_crs_for, reproject, valid_shapes
    from shapely.ops import unary_union

    target_fc = {"type": "FeatureCollection", "crs": "EPSG:4326",
                 "features": target_features}
    t_pairs = valid_shapes(target_fc, "target")
    r_pairs = valid_shapes(reference_fc, "near")
    if not t_pairs or not r_pairs:
        return []
    src_t, src_r = crs_of(target_fc), crs_of(reference_fc)
    metric = metric_crs_for([g for _, g in t_pairs] + [g for _, g in r_pairs])
    ref_union = unary_union([reproject(g, src_r, metric) for _, g in r_pairs])
    out = []
    for feat, geom in t_pairs:
        gm = reproject(geom, src_t, metric)
        if distance_m is not None:
            if gm.distance(ref_union) <= distance_m:
                out.append(feat)
        elif gm.intersects(ref_union):
            out.append(feat)
    return out


def _fetch_plain_pages(
    url: str, where: str, out_fields: str, return_geometry: bool,
    bbox_params: Dict[str, Any], max_features: int, page_size: int,
    pagination_supported: bool,
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """GET-based paged fetch with loop guards; returns (features, pages, info).

    Each request asks for at most ``page_size`` rows (``resultRecordCount``);
    ``resultOffset`` advances by rows received. Guards: ``MAX_PAGES_GUARD``,
    empty-page streak, and repeat-page detection (server ignoring
    ``resultOffset``). A failed page keeps earlier pages and records a
    partial-layer note instead of zeroing the URL.
    """
    per_layer: List[Dict[str, Any]] = []
    seen: set = set()
    url_pages = 0
    offset = 0
    empty_streak = 0
    stepped_down = False
    stopped_early: Optional[str] = None
    layer_note: Optional[str] = None
    while len(per_layer) < max_features:
        if url_pages >= MAX_PAGES_GUARD:
            stopped_early = f"page guard ({MAX_PAGES_GUARD})"
            break
        params: Dict[str, Any] = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "f": "geojson",
            "resultRecordCount": min(page_size, max_features - len(per_layer)),
            # County layers are natively wkid 103129 (Ohio North, feet);
            # force WGS84 so the frontend map plots correctly.
            "outSR": 4326,
        }
        params.update(bbox_params)
        if offset and pagination_supported:
            params["resultOffset"] = offset
        try:
            resp = requests.get(url.rstrip("/") + "/query", params=params,
                                timeout=TIMEOUT)
            resp.raise_for_status()
            page = _decode_json_dict(resp, url, "plain page")
            if "error" in page:
                raise RuntimeError(f"plain page: {page['error']}")
        except Exception as exc:
            if per_layer:
                layer_note = (f"{url}: kept {len(per_layer)} features "
                              f"before page error: {exc}")
                log.warning("partial layer fetch: %s", layer_note)
                break
            raise
        feats, exceeded = _features_of_page(page, url, "plain page")
        new = 0
        for feat in feats:
            key = _dedupe_key(feat)
            if key not in seen:
                seen.add(key)
                per_layer.append(feat)
                new += 1
        url_pages += 1
        if not feats:
            if (url_pages == 1 and offset == 0 and not stepped_down
                    and page_size > 100):
                # Same step-down as spatial pages: the county server
                # sometimes blanks on large record counts.
                page_size = max(100, page_size // 4)
                stepped_down = True
                log.info("query_arcgis %s: empty first page, stepping down "
                         "to page_size=%d", url, page_size)
                continue
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
        if feats and new == 0 and url_pages > 1:
            stopped_early = "server ignored resultOffset (repeat page)"
            break
        if not exceeded or len(per_layer) >= max_features:
            break
        if not pagination_supported:
            stopped_early = "pagination unsupported (single page)"
            break
        offset += len(feats)
        if offset >= max_features:
            break
    info: Dict[str, Any] = {}
    if stopped_early:
        info["stopped_early"] = stopped_early
    if layer_note:
        info["layer_note"] = layer_note
    return per_layer[:max_features], url_pages, info


def _spatial_total(url: str, core: Dict[str, Any], chunks) -> Optional[int]:
    """Best-effort server-side match count for the same spatial filter."""
    total = 0
    try:
        for geometry, geometry_type in chunks:
            params = dict(core, geometry=geometry, geometryType=geometry_type,
                          inSR=4326, spatialRel="esriSpatialRelIntersects",
                          returnCountOnly="true", f="json")
            page = _post_query(url, params)
            if "count" not in page:
                return None
            total += int(page["count"])
        return total
    except Exception:
        return None


def _dissolved_near_chunks(near, distance_m) -> Tuple[List[Tuple[str, str]], int, str]:
    """Build Esri POST chunks, dissolving the reference union when large.

    ANY-semantics are preserved either way (union == within ANY member).
    Returns (chunks, feature_count, method) with method 'union' or 'batched'.
    """
    from ..common import crs_of, reproject, valid_shapes

    raw_count = len((near.get("features") or []) if isinstance(near, dict) else [])
    pairs = [(f, g) for f, g in valid_shapes(near, "near") if not g.is_empty]
    if raw_count and not pairs:
        raise ValueError("reference area has no usable geometries "
                         "(all rows null or invalid)")
    if raw_count > len(pairs):
        log.info("near area: skipped %d null/invalid geometries of %d",
                 raw_count - len(pairs), raw_count)
    src = crs_of(near)
    if src != "EPSG:4326":
        pairs = [(f, reproject(g, src, "EPSG:4326")) for f, g in pairs]
    if not pairs:
        return [], 0, "empty"
    if len(pairs) > MAX_REFERENCE_FEATURES:
        raise ValueError(
            f"reference area has {len(pairs)} geometries (limit "
            f"{MAX_REFERENCE_FEATURES}); narrow with a bbox or place name"
        )
    # Prefer a single dissolved union: 1 POST chunk instead of N batches.
    if len(pairs) > NEAR_BATCH_SIZE:
        try:
            from shapely.ops import unary_union

            union = unary_union([g for _, g in pairs])
            dissolved = {"type": "FeatureCollection", "crs": "EPSG:4326",
                         "features": [{"type": "Feature", "properties": {},
                                       "geometry": __import__(
                                           "shapely.geometry", fromlist=["mapping"]
                                       ).mapping(union)}]}
            chunks, _ = _near_chunks(dissolved, distance_m)
            if chunks:
                log.info("near area dissolved: %d features -> %d chunk(s)",
                         len(pairs), len(chunks))
                return chunks, len(pairs), "union"
        except Exception as exc:
            log.info("near dissolve failed (%s); falling back to batching", exc)
    chunks, count = _near_chunks(near, distance_m)
    return chunks, count, "batched"


def _fetch_reference_by_name(
    ref_name: str, ref_max: int = 20000,
    _depth: int = 0,
) -> Dict[str, Any]:
    """Fetch a reference dataset by semantic name (paginated, no spatial filter)."""
    if _depth > 0:
        return {"ok": False,
                "error": "nested spatial_filter references are not supported"}
    return query_arcgis(ref_name, max_features=ref_max, _depth=_depth + 1)


def query_arcgis(
    dataset: str,
    where: str = "1=1",
    out_fields: str = "*",
    return_geometry: bool = True,
    max_features: int = 1000,
    bbox: Optional[str] = None,
    layer: Optional[int] = None,
    near: Any = None,
    distance_km: Optional[float] = None,
    page_size: Optional[int] = None,
    spatial_filter: Optional[Dict[str, Any]] = None,
    _depth: int = 0,
) -> Dict[str, Any]:
    """Query a registered ArcGIS dataset; returns a GeoJSON FeatureCollection.

    Pagination: ``page_size`` is the per-request ``resultRecordCount``
    (default 1000, ceiling ``PAGE_SIZE_MAX`` 2000); ``max_features`` is the
    total intent per layer URL (default 1000, historical default cap 2000,
    absolute ceiling ``ABSOLUTE_MAX_FEATURES`` 50000). Paging uses
    ``resultOffset`` until ``exceededTransferLimit`` clears, ``max_features``
    is reached, or loop guards trip. Any cap is reported via
    ``truncated``/``truncation_warning`` — never silent.

    Spatial: ``near`` (resolved ``$step`` FeatureCollection) + optional
    ``distance_km`` filters server-side (Esri ``Intersects`` + ``distance``
    in ``esriSRUnit_Meter``); only matching features are transferred.
    ``spatial_filter`` is the equivalent high-level form that keeps raw Esri
    params away from the planner::

        {"reference": "$floodplains" | FeatureCollection | "floodplains",
         "relationship": "within_distance" | "intersects",
         "distance": 2000, "units": "meters"}

    A bare dataset name as ``reference`` is auto-fetched (paginated) so a
    single-step plan can express layer-to-layer proximity. When the service
    lacks ``supportsQueryWithDistance``, the tool falls back to a *complete*
    paginated fetch + local metric computation (never a silent first-2000
    subset); the ``strategy`` field records which path ran.
    """
    from agent import registry as registry_module

    reg = registry_module.build_registry()
    if dataset not in reg:
        return {"ok": False, "error": f"unknown dataset '{dataset}'"}
    info = reg[dataset]
    if info.source_type != "arcgis_feature_server":
        return {
            "ok": False,
            "error": f"dataset '{dataset}' is not an ArcGIS source "
            f"(use {info.access_method})",
        }

    urls = _layer_urls(dataset, info.extra)
    if layer is not None and info.extra.get("layer4_url") and dataset == "floodplains":
        urls = [info.extra["layer4_url"]] if layer == 4 else urls[:1]
    if not urls and not _mock_enabled():
        return {
            "ok": False,
            "error": (
                f"dataset '{dataset}' is not configured: no ArcGIS layer URL "
                "provided (set ARCGIS_*_URL in .env). Capability unavailable."
            ),
            "code": "data_unavailable",
        }
    # ---- high-level spatial_filter -> near/distance_km (LLM decides WHAT) ----
    spatial_echo: Optional[Dict[str, Any]] = None
    try:
        near, distance_km, spatial_echo = _resolve_spatial_args(
            near, distance_km, spatial_filter)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    # Bare dataset-name reference: auto-fetch it (paginated) so the planner
    # can express "septic near floodplains" without a manual two-step plan.
    reference_fc: Optional[Dict[str, Any]] = None
    if isinstance(near, str) and not near.startswith("$"):
        ref_name = near
        if ref_name not in reg:
            return {"ok": False,
                    "error": f"spatial reference dataset '{ref_name}' unknown; "
                             f"known: {sorted(reg)}"}
        ref_max = 20000
        if isinstance(spatial_filter, dict):
            try:
                ref_max = max(1, min(int(spatial_filter.get(
                    "reference_max_features", ref_max)), ABSOLUTE_MAX_FEATURES))
            except (TypeError, ValueError):
                pass
        ref_res = _fetch_reference_by_name(ref_name, ref_max, _depth=_depth)
        if not ref_res.get("ok"):
            return {"ok": False,
                    "error": f"reference dataset '{ref_name}' fetch failed: "
                             f"{ref_res.get('error')}"}
        if ref_res.get("truncated"):
            return {
                "ok": False,
                "error": (
                    f"reference dataset '{ref_name}' truncated "
                    f"({ref_res.get('count')} of {ref_res.get('total_count')}); "
                    "narrow with a bbox or raise reference_max_features "
                    "instead of analysing a silent subset."
                ),
                "code": "reference_truncated",
                "reference_count": ref_res.get("count"),
                "reference_total": ref_res.get("total_count"),
            }
        reference_fc = ref_res
        near = ref_res
        if spatial_echo is not None:
            spatial_echo["reference_resolved"] = ref_res.get("count")
    if _mock_enabled():
        from .arcgis_mock import query_mock

        log.warning("ARCGIS_USE_MOCK=true: serving mock fixture for '%s'",
                    dataset)
        out = query_mock(dataset, where=where, bbox=bbox,
                         max_features=max_features, near=near,
                         distance_km=distance_km, page_size=page_size,
                         spatial_filter=spatial_filter)
        if spatial_echo is not None:
            out["spatial_filter"] = spatial_echo
            out.setdefault("strategy", "server_spatial" if near is not None
                           else "plain_paginated")
        return out

    # ---- validate proximity arguments (before any network I/O) ----
    distance_m: Optional[float] = None
    if distance_km is not None:
        if near is None:
            return {"ok": False, "error": "distance_km requires near"}
        try:
            distance_m = float(distance_km) * 1000.0
        except (TypeError, ValueError):
            return {"ok": False, "error": f"invalid distance_km '{distance_km}'"}
        if distance_m <= 0:
            return {"ok": False, "error": "distance_km must be positive"}
    chunks: List[Tuple[str, str]] = []
    near_count = 0
    chunk_method = "batched"
    if isinstance(near, str):
        return {"ok": False,
                "error": f"near must be a resolved FeatureCollection, got '{near}'"}
    if near is not None:
        if not isinstance(near, dict) or not isinstance(near.get("features"), list):
            return {"ok": False,
                    "error": "near must be a FeatureCollection result reference"}
        try:
            chunks, near_count, chunk_method = _dissolved_near_chunks(near, distance_m)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if near_count == 0:
            log.info("query_arcgis %s: empty near area, no fetch", dataset)
            return {"ok": True, "type": "FeatureCollection", "features": [],
                    "count": 0, "feature_count": 0, "dataset": dataset,
                    "geometry_type": "",
                    "truncated": False, "complete": True, "total_count": 0,
                    "truncation_warning": None, "pages": 0,
                    "per_url_counts": [], "layer_errors": [],
                    "strategy": "server_spatial_empty_reference",
                    "spatial_filter": spatial_echo or {
                        "relationship": "within_distance" if distance_m else "intersects",
                        "reference_count": 0},
                    "sources": [{"dataset": dataset, "url": u} for u in urls],
                    "note": "empty near area"}

    try:
        max_features = max(1, min(int(max_features), ABSOLUTE_MAX_FEATURES))
    except (TypeError, ValueError):
        return {"ok": False, "error": f"invalid max_features '{max_features}'"}
    try:
        page_size = max(1, min(int(page_size or PAGE_SIZE), PAGE_SIZE_MAX))
    except (TypeError, ValueError):
        return {"ok": False, "error": f"invalid page_size '{page_size}'"}
    bbox_params: Dict[str, Any] = {}
    if bbox and near is None:
        try:
            west, south, east, north = [float(x) for x in bbox.split(",")]
        except ValueError:
            return {"ok": False, "error": f"invalid bbox '{bbox}'"}
        bbox_params.update(
            {
                "geometry": f"{west},{south},{east},{north}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
            }
        )
    elif bbox and near is not None:
        log.info("query_arcgis %s: bbox ignored, near filter takes precedence",
                 dataset)
    log.debug("query_arcgis dataset=%s where=%s bbox=%s near_features=%s "
              "distance_km=%s max_features=%s page_size=%s urls=%d",
              dataset, where, bbox, near_count, distance_km,
              max_features, page_size, len(urls))

    def _fetch_one_url(url: str) -> Dict[str, Any]:
        """Fetch + filter a single layer URL (thread-safe; no shared state).

        Returns per-URL result; the caller merges in URL order so multi-URL
        output stays deterministic. Designed for concurrent execution: layer
        URLs are independent, and the county server is slow per request.
        """
        per_layer: List[Dict[str, Any]] = []
        url_pages = 0
        url_geometry_type = ""
        entry: Optional[Dict[str, Any]] = None
        url_strategy = "plain_paginated"
        layer_notes: List[str] = []
        page_notes_local: List[str] = []
        caps = get_layer_capabilities(url)
        pagination_supported = bool(caps.get("supportsPagination", False)) \
            or "unknown" in caps or caps.get("unknown", False) \
            or caps.get("supportsAdvancedQueries", False)
        # If the probe is inconclusive we still attempt resultOffset paging;
        # repeat-page detection below stops us if the server ignores it.
        if "unknown" in caps:
            pagination_supported = True
        distance_supported = bool(caps.get("supportsQueryWithDistance", False)) \
            or "unknown" in caps
        url_total: Optional[int] = None
        try:
            # Cheap server-side total so truncation is never silent.
            if near is not None:
                core_count = {"where": where}
                if distance_m:
                    core_count.update(distance=distance_m,
                                      units="esriSRUnit_Meter")
                subtotal = _spatial_total(url, core_count, chunks)
                if subtotal is not None:
                    url_total = subtotal
                    entry = {"url": url, "total": subtotal,
                             "fetched": 0, "pages": 0}
            else:
                try:
                    c_resp = requests.get(
                        url.rstrip("/") + "/query",
                        params={"where": where, "returnCountOnly": "true",
                                "f": "json"},
                        timeout=TIMEOUT,
                    )
                    c_payload = _decode_json_dict(
                        c_resp, url, "count probe")
                    if "count" in c_payload:
                        url_total = int(c_payload["count"])
                        entry = {"url": url, "total": url_total,
                                 "fetched": 0, "pages": 0}
                except Exception as exc:
                    log.warning("query_arcgis %s %s: count probe failed: %s",
                                dataset, url, exc)
                    pass  # totals are best-effort; the feature fetch decides ok/fail
            # Per-URL budget (not first-URL-wins): every layer URL returns up
            # to max_features, so e.g. floodplains MapServer/7 is never
            # starved by MapServer/6 filling a shared budget.
            if near is not None:
                if distance_m and not distance_supported:
                    # ---- correct fallback: complete paged fetch + local metric
                    # filter (ANY semantics), never a silent first-2000 slice.
                    log.info("query_arcgis %s %s: distance unsupported; "
                             "local fallback (paginated fetch + metric filter)",
                             dataset, url)
                    plain, plain_pages, _ = _fetch_plain_pages(
                        url, where, out_fields, return_geometry, bbox_params,
                        max_features, page_size, pagination_supported)
                    url_pages += plain_pages
                    kept = _local_within_distance_fallback(
                        plain, near, distance_m)
                    # Local matched totals replace the server total for URL.
                    if entry is not None:
                        entry["scanned"] = len(plain)
                        entry["matched"] = len(kept)
                        entry["total"] = len(kept)
                    else:
                        entry = {"url": url, "total": len(kept),
                                 "scanned": len(plain), "matched": len(kept),
                                 "fetched": 0, "pages": 0}
                    url_total = len(kept)
                    per_layer = kept[:max_features]
                    url_strategy = "local_fallback_distance_unsupported"
                else:
                    core = {"where": where,
                            "outFields": out_fields,
                            "returnGeometry": "true" if return_geometry else "false",
                            "outSR": 4326}
                    if distance_m:
                        core.update(distance=distance_m, units="esriSRUnit_Meter")
                    # Spatial queries POST form-encoded: geometries exceed URL limits.
                    try:
                        per_layer, url_pages, pg_info = _fetch_spatial_pages(
                            url, core, chunks, max_features, page_size,
                            pagination_supported=pagination_supported)
                    except Exception as exc:
                        # Server rejected the distance param (capability probe
                        # was inconclusive): retry as a correct local fallback
                        # instead of failing or returning a partial slice.
                        if distance_m and ("distance" in str(exc).lower()
                                           or "invalid" in str(exc).lower()):
                            log.info("query_arcgis %s %s: server rejected "
                                     "distance (%s); local fallback", dataset,
                                     url, exc)
                            plain, plain_pages, _ = _fetch_plain_pages(
                                url, where, out_fields, return_geometry,
                                bbox_params, max_features, page_size,
                                pagination_supported)
                            url_pages += plain_pages
                            _kept = _local_within_distance_fallback(
                                plain, near, distance_m)
                            if entry is not None:
                                entry["scanned"] = len(plain)
                                entry["matched"] = len(_kept)
                                entry["total"] = len(_kept)
                            else:
                                entry = {"url": url, "total": len(_kept),
                                         "scanned": len(plain),
                                         "matched": len(_kept),
                                         "fetched": 0, "pages": 0}
                            url_total = len(_kept)
                            per_layer = _kept[:max_features]
                            url_strategy = "local_fallback_distance_unsupported"
                        else:
                            raise RuntimeError(f"spatial fetch failed: {exc}") from exc
                    else:
                        url_strategy = "server_spatial"
                        if pg_info.get("stopped_early"):
                            page_notes_local.append(
                                f"{url}: {pg_info['stopped_early']}")
                            layer_notes.append(
                                f"{url}: paging stopped early "
                                f"({pg_info['stopped_early']}); kept "
                                f"{len(per_layer)} features")
            else:
                if bbox_params:
                    url_strategy = "server_spatial_bbox"
                per_layer, url_pages, pg_info = _fetch_plain_pages(
                    url, where, out_fields, return_geometry, bbox_params,
                    max_features, page_size, pagination_supported)
                if pg_info.get("stopped_early"):
                    page_notes_local.append(f"{url}: {pg_info['stopped_early']}")
                    layer_notes.append(
                        f"{url}: paging stopped early "
                        f"({pg_info['stopped_early']}); kept {len(per_layer)} "
                        "features")
            try:
                meta = describe_layer(url)
                url_geometry_type = meta.get("geometryType", "")
            except Exception as exc:  # metadata is best-effort
                log.warning("layer metadata fetch failed for %s: %s", url, exc)
            if entry is not None:
                entry["fetched"] = len(per_layer[:max_features])
                entry["pages"] = url_pages
            log.info("query_arcgis dataset=%s url=%s strategy=%s "
                     "offset_pages=%d fetched=%d/%s total=%s pagination=%s",
                     dataset, url, url_strategy, url_pages,
                     len(per_layer[:max_features]), max_features,
                     url_total,
                     "supported" if pagination_supported else "single-page")
            return {"url": url, "fatal": None,
                    "features": per_layer[:max_features],
                    "pages": url_pages, "strategy": url_strategy,
                    "geometry_type": url_geometry_type,
                    "total": url_total, "entry": entry,
                    "caps": caps, "pagination_supported": pagination_supported,
                    "layer_notes": layer_notes, "page_notes": page_notes_local}
        except Exception as exc:
            note = f"{url}: {type(exc).__name__}: {exc}"
            log.warning("layer fetch failed: %s", note)
            if entry is not None:
                entry["error"] = str(exc)[:200]
            return {"url": url, "fatal": note,
                    "features": [], "pages": 0, "strategy": "failed",
                    "geometry_type": "", "total": url_total, "entry": entry,
                    "caps": caps, "pagination_supported": False,
                    "layer_notes": [], "page_notes": []}

    def _probe_one_row(url: str) -> bool:
        """True if the layer yields at least one row (trust-but-verify zero).

        Single cheap request with the same filters. Used only when a full
        attempt came back empty with total==0, to distinguish an honestly
        empty result from a county-side flake.
        """
        try:
            if near is not None and chunks:
                core = {"where": where, "outFields": "OBJECTID",
                        "returnGeometry": "false", "outSR": 4326}
                if distance_m:
                    core.update(distance=distance_m, units="esriSRUnit_Meter")
                geom, kind = chunks[0]
                page = _post_query(url, dict(
                    core, geometry=geom, geometryType=kind, inSR=4326,
                    spatialRel="esriSpatialRelIntersects", f="geojson",
                    resultRecordCount=1))
                feats, _ = _features_of_page(page, url, "verify probe")
                return bool(feats)
            params = {"where": where, "outFields": "OBJECTID",
                      "returnGeometry": "false", "f": "geojson",
                      "resultRecordCount": 1, "outSR": 4326}
            params.update(bbox_params)
            resp = requests.get(url.rstrip("/") + "/query", params=params,
                                timeout=TIMEOUT)
            resp.raise_for_status()
            feats, _ = _decode_feature_page(resp, url, "verify probe")
            return bool(feats)
        except Exception as exc:
            log.info("query_arcgis %s %s: verify probe failed: %s",
                     dataset, url, exc)
            return False

    def _attempt_with_retry(url: str) -> Dict[str, Any]:
        """One conditional retry for flaky empty results.

        The county server intermittently answers valid requests with empty
        pages (or a failed count probe) while the sibling layer succeeds. If
        an attempt yields zero rows while the count probe promised some —
        or the probe itself failed — wait briefly and try once more rather
        than reporting a silent incomplete zero. A zero total is verified
        with a one-row probe first, so honestly empty results stay silent
        while lying zeros are retried and then flagged.
        """
        res = _fetch_one_url(url)
        expected = res.get("total")
        if (not res.get("fatal") and not res.get("features")
                and (expected is None or expected > 0)):
            log.info("query_arcgis %s %s: empty despite total=%s; retrying once",
                     dataset, url, expected)
            time.sleep(2.0)
            retry = _fetch_one_url(url)
            if retry.get("features") or retry.get("fatal"):
                return retry
            # Retry equally empty: keep the original but flag the mismatch.
            if expected:
                res["layer_notes"].append(
                    f"{url}: server reported {expected} but returned 0 rows "
                    "(possible service flake); narrow with a bbox and retry")
            else:
                res["layer_notes"].append(
                    f"{url}: count probe failed and 0 rows retrieved "
                    "(possible service flake)")
            return res
        if (not res.get("fatal") and not res.get("features")
                and expected == 0 and _probe_one_row(url)):
            log.info("query_arcgis %s %s: zero total contradicted by probe; "
                     "retrying once", dataset, url)
            time.sleep(2.0)
            retry = _fetch_one_url(url)
            if retry.get("features") or retry.get("fatal"):
                return retry
            res["layer_notes"].append(
                f"{url}: server reported 0 but a one-row probe found data "
                "(possible service flake); narrow with a bbox and retry")
        return res

    all_features: List[Dict[str, Any]] = []
    geometry_type = ""
    errors: List[str] = []        # fatal per-URL failures (no features kept)
    layer_errors: List[str] = []  # partial failures (kept what we could)
    total_count: Optional[int] = None  # server-side total (returnCountOnly sum)
    total_pages = 0
    per_url_counts: List[Dict[str, Any]] = []
    capabilities_by_url: Dict[str, Dict[str, Any]] = {}
    strategies: List[str] = []
    page_notes: List[str] = []
    # Layer URLs are independent: fetch concurrently (executor.map preserves
    # URL order, so merged output stays deterministic). The county server is
    # slow per request (~seconds), so this roughly halves wall time.
    if len(urls) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(
                max_workers=min(4, len(urls))) as _pool:
            url_results = list(_pool.map(_attempt_with_retry, urls))
    else:
        url_results = [_attempt_with_retry(u) for u in urls]
    for res in url_results:
        capabilities_by_url[res["url"]] = res["caps"]
        if res.get("fatal"):
            errors.append(res["fatal"])
            if res.get("entry") is not None:
                per_url_counts.append(res["entry"])
            continue
        strategies.append(res["strategy"])
        all_features.extend(res["features"])
        if res.get("total") is not None:
            total_count = (res["total"] if total_count is None
                           else total_count + res["total"])
        if res.get("entry") is not None:
            per_url_counts.append(res["entry"])
        layer_errors.extend(res["layer_notes"])
        page_notes.extend(res["page_notes"])
        total_pages += res["pages"]
        geometry_type = geometry_type or res["geometry_type"]

    if not all_features and errors:
        return {"ok": False, "error": "; ".join(errors), "code": "data_unavailable"}

    capped = max_features * max(1, len(urls))
    fetched = all_features[:capped]
    # Reconcile local-fallback totals: matched counts are exact for the
    # fetched window; server totals (if any) still bound completeness.
    truncated = (total_count is not None and len(fetched) < total_count) \
        or len(fetched) >= capped
    # Edge: exactly max_features fetched with no server total and no
    # exceededTransferLimit signal -> may still be complete (Test 2). Only
    # flag the cap when we actually stopped due to the budget.
    if truncated:
        if total_count is not None and len(fetched) < total_count:
            warning = (f"{dataset} query truncated at {len(fetched)} of "
                       f"{total_count} features; results may be incomplete.")
        else:
            warning = (f"{dataset} query hit the {capped}-feature cap; "
                       "results may be incomplete.")
        log.warning("truncation: %s", warning)
    else:
        warning = None
    strategy = strategies[0] if len(set(strategies)) == 1 else (
        "mixed:" + ",".join(sorted(set(strategies))) if strategies else "unknown")
    if spatial_echo is None and near is not None:
        spatial_echo = {
            "relationship": "within_distance" if distance_m else "intersects",
            "distance_km": distance_km,
            "reference_count": near_count,
            "reference_method": chunk_method,
        }
    elif isinstance(spatial_echo, dict) and near is not None:
        spatial_echo = {**spatial_echo, "reference_count": near_count,
                        "reference_method": chunk_method,
                        "distance_km": distance_km}
    return {
        "ok": True,
        "type": "FeatureCollection",
        "features": fetched,
        "count": len(fetched),
        "feature_count": len(fetched),
        "dataset": dataset,
        "geometry_type": geometry_type,
        "truncated": truncated,
        "complete": (not truncated and not layer_errors and not errors),
        "total_count": total_count,
        "truncation_warning": warning,
        "pages": total_pages,
        "per_url_counts": per_url_counts,
        "layer_errors": layer_errors,
        "strategy": strategy,
        "spatial_filter": spatial_echo,
        "pagination": {"page_size": page_size, "max_features": max_features,
                       "pages": total_pages, "page_notes": page_notes},
        "capabilities": capabilities_by_url,
        "sources": [{"dataset": dataset, "url": u} for u in urls],
    }


QUERY_ARCGIS_SCHEMA = {
    "properties": {
        "dataset": {
            "type": "string",
            "description": "Semantic dataset name: 'septic_systems' or 'floodplains'.",
        },
        "where": {
            "type": "string",
            "description": "Optional SQL where clause, e.g. 'STATUS = 1'. Default '1=1'.",
        },
        "out_fields": {
            "type": "string",
            "description": "Comma-separated fields or '*' (default).",
        },
        "return_geometry": {
            "type": "boolean",
            "description": "Return geometries (default true).",
        },
        "max_features": {
            "type": "integer",
            "description": "Total features wanted per layer URL (default 1000; "
                           "pages automatically with page_size until this "
                           "total, the server is exhausted, or the 50000 "
                           "safety ceiling; multi-URL datasets return up to "
                           "max per URL). NOT a silent subset: truncation is "
                           "reported via truncated/total_count.",
        },
        "page_size": {
            "type": "integer",
            "description": "Per-request service page size (resultRecordCount; "
                           "default 1000, ceiling 2000).",
        },
        "bbox": {
            "type": "string",
            "description": "Optional 'west,south,east,north' (EPSG:4326) spatial filter.",
        },
        "near": {
            "description": "Optional $step reference to a FeatureCollection "
                           "defining the search area server-side "
                           "(e.g. \"$floodplains\").",
        },
        "distance_km": {
            "type": "number",
            "description": "Optional proximity radius in kilometres around "
                           "near (server-side distance + esriSRUnit_Meter).",
        },
        "spatial_filter": {
            "description": "High-level alternative to near/distance_km: "
                           "{\"reference\": \"$step\"|FeatureCollection|"
                           "\"dataset_name\", \"relationship\": "
                           "\"within_distance\"|\"intersects\", \"distance\": "
                           "number, \"units\": \"meters\"|\"kilometers\"|"
                           "\"feet\"|\"miles\"}. Server-side filtering is "
                           "preferred; local metric fallback is automatic "
                           "when the service lacks distance support.",
        },
    }
}
QUERY_ARCGIS_REQUIRED = ["dataset"]
