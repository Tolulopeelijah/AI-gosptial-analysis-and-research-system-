"""Mock-backed fixtures for the three Lucas County ArcGIS layers.

Why this exists: the live FeatureServer endpoints are unreachable from this
environment (connection timeouts on every attempt), and their layer metadata
(`?f=json`) could therefore not be inspected. Per project requirements the
tools keep their real ArcGIS REST interface, but responses are served from
these fixtures while ``ARCGIS_USE_MOCK=true``.

PROVISIONAL SCHEMA (documented, not presented as real):
  * Geometry types are assumed from layer names — septic systems as Points,
    floodplain areas as Polygons — and MUST be verified against live metadata
    when the servers become reachable.
  * Attributes are a minimal representative set: OBJECTID (universal in Esri
    services) plus one generic field per layer (STATUS / ZONE). The real field
    lists are unknown. Every mock response carries ``provisional_schema:
    true`` and the ``live_url`` it stands in for.
  * Coordinates are plausible Lucas County, Ohio locations (EPSG:4326), NOT
    real records. Fixture geometry is arranged so demos are meaningful: some
    septic points fall inside the floodplain polygons, some do not.

Switching to live: set ``ARCGIS_USE_MOCK=false`` — no code changes needed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

MOCK_NOTE = (
    "Mock-backed response (ARCGIS_USE_MOCK=true): structurally representative "
    "fixture, not live county data. Provisional schema — verify against live "
    "layer metadata before research use."
)

# ---------------------------------------------------------------- fixtures ---

_SEPTIC_POINTS = [
    (-83.85, 41.60), (-83.80, 41.63), (-83.75, 41.58), (-83.70, 41.66),
    (-83.65, 41.61), (-83.60, 41.68), (-83.55, 41.59), (-83.50, 41.64),
    (-83.45, 41.62), (-83.90, 41.66),
]

_FLOODPLAIN_POLYS = [
    {   # Maumee River corridor (overlaps 3 septic fixtures)
        "ring": [[-83.62, 41.58], [-83.48, 41.58], [-83.48, 41.70],
                 [-83.62, 41.70], [-83.62, 41.58]],
        "zone": "AE",
    },
    {   # Swan Creek area (overlaps none of the fixtures)
        "ring": [[-83.80, 41.52], [-83.70, 41.52], [-83.70, 41.57],
                 [-83.80, 41.57], [-83.80, 41.52]],
        "zone": "X",
    },
]


def _live_urls(dataset: str) -> List[str]:
    from ...config import settings

    if dataset == "septic_systems":
        return [settings.ARCGIS_SEPTIC_URL] if settings.ARCGIS_SEPTIC_URL else []
    if dataset == "floodplains":
        return [u for u in (settings.ARCGIS_FLOODPLAIN_0_URL,
                            settings.ARCGIS_FLOODPLAIN_4_URL) if u]
    return []


def septic_fixture() -> List[Dict[str, Any]]:
    feats = []
    for i, (lon, lat) in enumerate(_SEPTIC_POINTS, 1):
        feats.append({
            "type": "Feature",
            "properties": {"OBJECTID": i, "STATUS": "Active"},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })
    return feats


def floodplain_fixture() -> List[Dict[str, Any]]:
    feats = []
    for i, poly in enumerate(_FLOODPLAIN_POLYS, 1):
        feats.append({
            "type": "Feature",
            "properties": {"OBJECTID": i, "ZONE": poly["zone"]},
            "geometry": {"type": "Polygon", "coordinates": [poly["ring"]]},
        })
    return feats


def describe_mock(dataset: str) -> Dict[str, Any]:
    """Esri-style layer metadata for fixtures (provisional)."""
    base = {
        "septic_systems": {
            "name": "SEPTIC_SYSTEM_VIEW (mock)",
            "geometryType": "esriGeometryPoint",
            "fields": [
                {"name": "OBJECTID", "type": "esriFieldTypeOID", "alias": "OBJECTID"},
                {"name": "STATUS", "type": "esriFieldTypeString", "alias": "STATUS (provisional)"},
            ],
        },
        "floodplains": {
            "name": "FLOODPLAIN_VIEW (mock)",
            "geometryType": "esriGeometryPolygon",
            "fields": [
                {"name": "OBJECTID", "type": "esriFieldTypeOID", "alias": "OBJECTID"},
                {"name": "ZONE", "type": "esriFieldTypeString", "alias": "ZONE (provisional)"},
            ],
        },
    }.get(dataset)
    if base is None:
        raise ValueError(f"unknown dataset '{dataset}'")
    return {
        **base,
        "field_names": [f["name"] for f in base["fields"]],
        "spatialReference": {"wkid": 4326},
        "capabilities": "Query (mock)",
        "supportsPagination": True,
        "supportsQueryWithDistance": MOCK_DISTANCE_SUPPORTED,
        "supportsAdvancedQueries": True,
        "maxRecordCount": 2000,
        "provisional_schema": True,
        "mocked": True,
        "live_urls": _live_urls(dataset),
    }


# Absolute safety ceiling mirrored from the live tool (tests may raise
# totals above the historical 2000 default via max_features + paging).
MOCK_ABSOLUTE_MAX = 50000
# When True, the mock pretends the server lacks distance support so tests
# can verify the local-fallback path (mirrors supportsQueryWithDistance).
MOCK_DISTANCE_SUPPORTED = True


def query_mock(
    dataset: str,
    where: str = "1=1",
    bbox: Optional[str] = None,
    max_features: int = 1000,
    near: Any = None,
    distance_km: Optional[float] = None,
    page_size: Optional[int] = None,
    spatial_filter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Serve a fixture FeatureCollection honouring bbox + limit.

    ``where`` is accepted for interface compatibility; the mock only
    understands ``1=1`` and simple ``OBJECTID = N`` predicates (anything
    else is noted as not applied).

    ``near``/``distance_km`` mirror the live server-side spatial filter:
    fixtures are filtered locally against the ``near`` FeatureCollection
    (buffered by ``distance_km`` when given) so mock and live behave alike.
    ``spatial_filter`` is normalised the same way as live (reference may be
    a dataset name, $ref string, or FeatureCollection).
    ``page_size`` pages the filtered list the way the live paged fetch
    does; the assembled result is identical, only ``pages`` differs.
    ``max_features`` is the total intent (default 1000, ceiling
    ``MOCK_ABSOLUTE_MAX``); the historical 2000 default is NOT a hard cap.
    When ``MOCK_DISTANCE_SUPPORTED`` is False and a distance is requested,
    the mock records ``strategy: local_fallback_distance_unsupported`` to
    exercise the fallback branch explicitly.
    """
    # Normalise high-level spatial_filter (same mapping as live).
    spatial_echo = None
    if spatial_filter is not None:
        if not isinstance(spatial_filter, dict):
            return {"ok": False, "error": "spatial_filter must be an object"}
        ref = spatial_filter.get("reference", spatial_filter.get("reference_dataset"))
        rel = (spatial_filter.get("relationship") or "within_distance").lower()
        if rel not in ("within_distance", "intersects"):
            return {"ok": False, "error": f"unknown spatial relationship '{rel}'"}
        dist, units = spatial_filter.get("distance"), (
            spatial_filter.get("units") or "meters").lower()
        dist_km = None
        if rel == "within_distance":
            if dist is None:
                return {"ok": False, "error": "spatial_filter needs 'distance'"}
            factors = {"meters": 1.0, "kilometers": 1000.0, "km": 1000.0,
                       "feet": 0.3048, "miles": 1609.344, "m": 1.0,
                       "mi": 1609.344, "ft": 0.3048}
            if units not in factors:
                return {"ok": False, "error": f"unknown units '{units}'"}
            dist_km = float(dist) * factors[units] / 1000.0
        spatial_echo = {"relationship": rel, "distance": dist, "units": units,
                        "reference": ref if isinstance(ref, str) else "FeatureCollection"}
        if near is None:
            if isinstance(ref, str) and not ref.startswith("$"):
                # dataset-name reference: resolve from fixtures (paginated).
                other = query_mock(ref, max_features=MOCK_ABSOLUTE_MAX)
                if not other.get("ok"):
                    return {"ok": False,
                            "error": f"reference dataset '{ref}' failed: "
                                     f"{other.get('error')}"}
                near = {"type": "FeatureCollection", "crs": "EPSG:4326",
                        "features": other["features"]}
            else:
                near = ref
        if distance_km is None:
            distance_km = dist_km
        if rel == "intersects":
            distance_km = None
    if dataset == "septic_systems":
        feats = septic_fixture()
        geometry_type = "esriGeometryPoint"
    elif dataset == "floodplains":
        feats = floodplain_fixture()
        geometry_type = "esriGeometryPolygon"
    else:
        return {"ok": False, "error": f"unknown dataset '{dataset}'"}

    where_note = ""
    predicate = (where or "1=1").strip()
    if predicate != "1=1":
        import re

        m = re.match(r"(?i)^\s*OBJECTID\s*=\s*(\d+)\s*$", predicate)
        if m:
            oid = int(m.group(1))
            feats = [f for f in feats if f["properties"].get("OBJECTID") == oid]
            where_note = f"mock applied predicate {predicate}"
        else:
            where_note = (
                f"mock does not evaluate predicate '{predicate}'; "
                "returned unfiltered fixture"
            )

    if bbox:
        try:
            west, south, east, north = [float(x) for x in bbox.split(",")]
        except ValueError:
            return {"ok": False, "error": f"invalid bbox '{bbox}'"}
        kept = []
        for f in feats:
            g = f["geometry"]
            coords = g["coordinates"] if g["type"] == "Point" else g["coordinates"][0]
            xs = [c[0] for c in (coords if g["type"] != "Point" else [coords])]
            ys = [c[1] for c in (coords if g["type"] != "Point" else [coords])]
            if max(xs) >= west and min(xs) <= east and max(ys) >= south and min(ys) <= north:
                kept.append(f)
        feats = kept

    try:
        max_features = max(1, min(int(max_features), MOCK_ABSOLUTE_MAX))
    except (TypeError, ValueError):
        return {"ok": False, "error": f"invalid max_features '{max_features}'"}
    total = len(feats)
    strategy = "plain_paginated"

    # Server-side spatial filter (mirrors live `near`/`distance_km`).
    if isinstance(near, str):
        return {"ok": False,
                "error": f"near must be a resolved FeatureCollection, got '{near}'"}
    if near is not None:
        from ..gis.operations import buffer as _buffer, intersect as _intersect

        search_area = near if isinstance(near, dict) else {"features": []}
        if distance_km is not None:
            try:
                distance_km = float(distance_km)
            except (TypeError, ValueError):
                return {"ok": False,
                        "error": f"invalid distance_km '{distance_km}'"}
            if distance_km <= 0:
                return {"ok": False, "error": "distance_km must be positive"}
            search_area = _buffer(search_area, distance_km, unit="kilometers")
            if not search_area.get("ok", True):
                return {"ok": False,
                        "error": search_area.get("error", "buffer failed")}
        if not search_area.get("features"):
            feats = []
        else:
            filtered = _intersect(
                {"type": "FeatureCollection", "crs": "EPSG:4326",
                 "features": feats},
                search_area)
            feats = filtered.get("features", [])
        total = len(feats)

    # Paged assembly (mirrors the live resultOffset loop, with page-size cap).
    try:
        page_size = max(1, min(int(page_size or 1000), 2000))
    except (TypeError, ValueError):
        return {"ok": False, "error": f"invalid page_size '{page_size}'"}
    if near is not None and distance_km is not None and not MOCK_DISTANCE_SUPPORTED:
        strategy = "local_fallback_distance_unsupported"
    elif near is not None:
        strategy = "server_spatial"
    pages, assembled = 0, []
    guard = 0
    while len(assembled) < min(total, max_features):
        guard += 1
        if guard > 100:
            break
        assembled.extend(feats[len(assembled):len(assembled) + page_size])
        pages += 1
        if pages > 1 and not assembled[-1:]:
            break
    feats = assembled[:max_features]
    truncated = total > len(feats)
    warning = (f"{dataset} query truncated at {len(feats)} of {total} "
               "features; results may be incomplete." if truncated else None)
    return {
        "ok": True,
        "type": "FeatureCollection",
        "features": feats,
        "count": len(feats),
        "feature_count": len(feats),
        "dataset": dataset,
        "geometry_type": geometry_type,
        "crs": "EPSG:4326",
        "mocked": True,
        "provisional_schema": True,
        "live_urls": _live_urls(dataset),
        "note": MOCK_NOTE + (f" {where_note}" if where_note else ""),
        "truncated": truncated,
        "complete": not truncated,
        "total_count": total,
        "truncation_warning": warning,
        "pages": pages,
        "strategy": strategy,
        "spatial_filter": spatial_echo,
        "pagination": {"page_size": page_size, "max_features": max_features,
                       "pages": pages},
    }
