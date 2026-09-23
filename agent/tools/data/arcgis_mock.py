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
        "provisional_schema": True,
        "mocked": True,
        "live_urls": _live_urls(dataset),
    }


def query_mock(
    dataset: str,
    where: str = "1=1",
    bbox: Optional[str] = None,
    max_features: int = 1000,
) -> Dict[str, Any]:
    """Serve a fixture FeatureCollection honouring bbox + limit.

    ``where`` is accepted for interface compatibility; the mock only
    understands ``1=1`` and simple ``OBJECTID = N`` predicates (anything
    else is noted as not applied).
    """
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

    max_features = max(1, min(int(max_features), 2000))
    feats = feats[:max_features]
    return {
        "ok": True,
        "type": "FeatureCollection",
        "features": feats,
        "count": len(feats),
        "dataset": dataset,
        "geometry_type": geometry_type,
        "crs": "EPSG:4326",
        "mocked": True,
        "provisional_schema": True,
        "live_urls": _live_urls(dataset),
        "note": MOCK_NOTE + (f" {where_note}" if where_note else ""),
    }
