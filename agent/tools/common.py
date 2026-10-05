"""Shared helpers for tool implementations.

Conventions every capability module follows:

* Tool functions take JSON-native arguments and return plain dicts with
  ``ok: True/False``. ``Tool.run`` converts raised exceptions into
  structural failures, so helpers raise ``ToolError``/``CapabilityError``
  with useful messages instead of returning ad-hoc shapes.
* Geographic inputs/outputs are GeoJSON FeatureCollections in EPSG:4326
  unless a ``crs`` member says otherwise. Anything accepting ``$step_id``
  receives the resolved payload from the orchestrator — tools never resolve
  refs themselves.
* Metric work (buffers, areas, lengths, metric distances) reprojects to a
  local projected CRS first (see ``metric_crs_for``); degrees are never
  treated as metres.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class ToolError(ValueError):
    """Invalid arguments or unusable inputs for a tool."""


class CapabilityError(RuntimeError):
    """The capability exists but cannot run here (missing optional
    dependency, unconfigured provider, or unreachable service). Carries a
    ``hint`` telling the operator what would enable it."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


def require_module(import_name: str, pip_name: str = ""):
    """Import an optional dependency or raise a clear CapabilityError."""
    try:
        import importlib

        return importlib.import_module(import_name)
    except ImportError as exc:
        raise CapabilityError(
            f"capability unavailable: optional dependency "
            f"'{pip_name or import_name}' is not installed",
            hint=f"install it with: pip install {pip_name or import_name}",
        ) from exc


def fail(error: str, code: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "error": error}
    if code:
        out["code"] = code
    return out


def features_of(fc: Dict[str, Any], name: str = "input") -> List[Dict[str, Any]]:
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection" \
            or not isinstance(fc.get("features"), list):
        raise ToolError(f"'{name}' must be a GeoJSON FeatureCollection")
    return fc["features"]


def parse_geom(obj: Any, name: str = "geometry"):
    """Shapely geometry from a GeoJSON geometry or Feature, repaired."""
    from shapely.geometry import shape
    from shapely.validation import make_valid

    if not isinstance(obj, dict):
        raise ToolError(f"invalid {name}: not an object")
    g = obj.get("geometry", obj) if obj.get("type") == "Feature" else obj
    if g is None:
        # County layers contain rows with null geometry; the key exists so
        # .get's default does NOT apply — check explicitly and skip via
        # valid_shapes instead of crashing with AttributeError on None.
        raise ToolError(f"{name} is null (row has no geometry)")
    try:
        geom = shape(g)
    except Exception as exc:
        raise ToolError(f"invalid {name}: {exc}") from exc
    if not geom.is_valid:
        geom = make_valid(geom)
    if geom.is_empty:
        raise ToolError(f"{name} is empty after validation")
    return geom


def valid_shapes(fc: Dict[str, Any],
                 name: str = "input") -> List[Tuple[Dict[str, Any], Any]]:
    """(feature, repaired shapely geometry) pairs, skipping empties."""
    from shapely.validation import make_valid

    out = []
    for feat in features_of(fc, name):
        if not isinstance(feat, dict):
            continue  # county servers occasionally emit null array entries
        try:
            geom = parse_geom(feat.get("geometry", {}), name)
        except ToolError:
            continue
        if not geom.is_valid:
            geom = make_valid(geom)
        if not geom.is_empty:
            out.append((feat, geom))
    return out


def crs_of(fc: Dict[str, Any]) -> str:
    return (fc.get("crs") if isinstance(fc, dict) else None) or "EPSG:4326"


def metric_crs_for(geoms) -> str:
    """Local projected CRS centred on the data (UTM, else azimuthal)."""
    from shapely.ops import unary_union

    from pyproj import CRS

    merged = unary_union(list(geoms))
    lon, lat = merged.centroid.x, merged.centroid.y
    bounds = merged.bounds
    try:
        if max(bounds[2] - bounds[0], bounds[3] - bounds[1]) < 6:
            zone = int((lon + 180) // 6) + 1
            return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"
    except Exception:
        pass
    _ = CRS("EPSG:4326")  # validates pyproj availability early
    return (f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 "
            "+ellps=WGS84 +datum=WGS84 +units=m +no_defs")


def reproject(geom, src: str, dst: str):
    if src == dst:
        return geom
    from pyproj import CRS, Transformer
    from shapely.ops import transform as shp_transform

    transformer = Transformer.from_crs(CRS(src), CRS(dst), always_xy=True)
    return shp_transform(transformer.transform, geom)


def to_wgs_feature(geom, properties: Dict[str, Any], src_crs: str) -> Dict[str, Any]:
    from shapely.geometry import mapping

    return {"type": "Feature", "properties": properties,
            "geometry": mapping(reproject(geom, src_crs, "EPSG:4326"))}


def collection(features: List[Dict[str, Any]], **meta) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": True, "type": "FeatureCollection",
                           "features": features, "count": len(features),
                           "crs": "EPSG:4326"}
    out.update(meta)
    return out


def table(columns: List[str], rows: List[Dict[str, Any]], **meta) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": True, "type": "table", "columns": columns,
                           "rows": rows, "row_count": meta.get("row_count", len(rows))}
    out.update(meta)
    return out


def cap_int(value: Any, default: int, maximum: int, name: str = "limit") -> int:
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        if value is None:
            return max(1, min(default, maximum))
        raise ToolError(f"'{name}' must be an integer")


def parse_bbox(bbox: str) -> Tuple[float, float, float, float]:
    try:
        west, south, east, north = (float(x) for x in str(bbox).split(","))
    except ValueError:
        raise ToolError(f"invalid bbox '{bbox}'; use 'west,south,east,north'")
    if not (west < east and south < north):
        raise ToolError(f"invalid bbox '{bbox}'; need west<east, south<north")
    return west, south, east, north


DISTANCE_FACTORS = {"meters": 1.0, "kilometers": 1000.0, "km": 1000.0,
                    "feet": 0.3048, "miles": 1609.344}


def to_meters(distance: float, unit: str) -> float:
    if unit not in DISTANCE_FACTORS:
        raise ToolError(f"unknown unit '{unit}'; use meters|kilometers|feet|miles")
    if distance <= 0:
        raise ToolError("distance must be positive")
    return float(distance) * DISTANCE_FACTORS[unit]


def http_get(url: str, params: Optional[Dict[str, Any]] = None,
             timeout: int = 30, headers: Optional[Dict[str, str]] = None):
    """requests.get with a clear capability error on network failure."""
    require_module("requests", "requests")
    import requests

    try:
        resp = requests.get(url, params=params, timeout=timeout,
                            headers={"User-Agent": "weis-geospatial-agent/1.0",
                                     **(headers or {})})
        resp.raise_for_status()
        return resp
    except Exception as exc:
        raise CapabilityError(f"request to {url} failed: {exc}",
                              hint="check network access and service status") from exc
