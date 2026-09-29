"""Remote sensing: STAC search plus spectral indices on raster bands.

`stac_search` queries the Microsoft Planetary Computer STAC API (no key) for
Sentinel-2/Landsat scenes over an area and time range, returning item
metadata and asset URLs — discovery, not download. Index tools compute real
band math on single-band raster references/paths produced by the raster
tools (e.g. load two bands, then NDVI, then reclassify, then zonal stats).
"""

from __future__ import annotations

from typing import Any, Dict

from ..common import CapabilityError, ToolError, cap_int, http_get, parse_bbox

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
COLLECTIONS = ("sentinel-2-l2a", "landsat-c2-l2")


def stac_search(bbox: str, start: str, end: str,
                collection: str = "sentinel-2-l2a", max_items: int = 20,
                max_cloud_cover: float = 20.0):
    """Find satellite scenes (bbox + date range) with asset URLs."""
    import requests

    if collection not in COLLECTIONS:
        raise ToolError(f"collection must be one of {', '.join(COLLECTIONS)}")
    w, s, e, n = parse_bbox(bbox)
    try:
        from datetime import date

        assert date.fromisoformat(start) <= date.fromisoformat(end)
    except (ValueError, AssertionError):
        raise ToolError("start/end must be ISO dates with start <= end")
    if not (0 <= max_cloud_cover <= 100):
        raise ToolError("max_cloud_cover must be 0..100")
    max_items = cap_int(max_items, 1, 100, name="max_items")
    body = {"collections": [collection], "bbox": [w, s, e, n],
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lt": max_cloud_cover}},
            "limit": max_items}
    try:
        resp = requests.post(STAC_URL, json=body, timeout=60,
                             headers={"User-Agent": "weis-geospatial-agent/1.0"})
        resp.raise_for_status()
        doc = resp.json()
    except Exception as exc:
        raise CapabilityError(f"STAC search failed: {exc}") from exc
    items = []
    for feat in doc.get("features", [])[:max_items]:
        props = feat.get("properties", {})
        assets = feat.get("assets", {}) or {}
        items.append({"id": feat.get("id"),
                      "datetime": props.get("datetime"),
                      "cloud_cover_pct": (props.get("eo:cloud_cover")
                                          or props.get("cloud_cover")),
                      "bands": sorted(assets),
                      "asset_hrefs": {k: v.get("href") for k, v in assets.items()
                                      if v.get("href")}})
    return {"ok": True, "collection": collection, "items": items,
            "count": len(items),
            "note": "scene discovery only; use raster tools on downloaded bands"}


def _single_band(input: Any, name: str) -> str:
    from ..raster.raster import _describe, _resolve, _rio

    rio = _rio()
    path = _resolve(input)
    with rio.open(path) as src:
        if src.count < 1:
            raise ToolError(f"{name} raster is empty")
    _ = _describe
    return path


def _normalised_index(path_a: str, path_b: str, label: str,
                      l_factor: float = 0.0):
    from ..raster.raster import _describe, _out_path, _resolve, _rio

    import numpy as np

    rio = _rio()
    pa, pb = _resolve(path_a), _resolve(path_b)
    with rio.open(pa) as src:
        a = src.read(1).astype("float64")
        meta = src.meta.copy()
    with rio.open(pb) as src:
        b = src.read(1).astype("float64")
        if b.shape != a.shape:
            raise ToolError(f"band shape mismatch {a.shape} vs {b.shape}")
    with np.errstate(divide="ignore", invalid="ignore"):
        if l_factor:
            out = ((a - b) / (a + b + l_factor)) * (1 + l_factor)
        else:
            denom = a + b
            out = np.where(denom != 0, (a - b) / denom, np.nan)
    meta.update({"count": 1, "dtype": "float64", "nodata": -9999.0})
    dest = _out_path(label.lower())
    with rio.open(dest, "w", **meta) as dst:
        dst.write(np.nan_to_num(out, nan=-9999.0), 1)
    return {"ok": True, "type": "raster", **_describe(dest, rio),
            "index": label, "range": "[-1, 1]"}


def calculate_ndvi(nir: Any, red: Any):
    """NDVI = (NIR − Red) / (NIR + Red), vegetation vigour in [-1, 1]."""
    return _normalised_index(_single_band(nir, "nir"), _single_band(red, "red"),
                             "NDVI")


def calculate_ndwi(nir: Any, green: Any):
    """McFeeters NDWI = (Green − NIR) / (Green + NIR), open water in [-1, 1]."""
    return _normalised_index(_single_band(green, "green"),
                             _single_band(nir, "nir"), "NDWI")


def calculate_ndbi(swir: Any, nir: Any):
    """NDBI = (SWIR − NIR) / (SWIR + NIR), built-up likelihood in [-1, 1]."""
    return _normalised_index(_single_band(swir, "swir"),
                             _single_band(nir, "nir"), "NDBI")


SENSING_SCHEMAS = {
    "stac_search": ({"properties": {
        "bbox": {"type": "string"},
        "start": {"type": "string", "description": "ISO date."},
        "end": {"type": "string", "description": "ISO date."},
        "collection": {"type": "string",
                       "description": "sentinel-2-l2a (default) or landsat-c2-l2."},
        "max_items": {"type": "integer"},
        "max_cloud_cover": {"type": "number", "description": "Percent (default 20)."}}},
        ["bbox", "start", "end"]),
    "calculate_ndvi": ({"properties": {
        "nir": {"description": "NIR band raster reference or path."},
        "red": {"description": "Red band raster reference or path."}}},
        ["nir", "red"]),
    "calculate_ndwi": ({"properties": {
        "nir": {"description": "NIR band reference or path."},
        "green": {"description": "Green band reference or path."}}},
        ["nir", "green"]),
    "calculate_ndbi": ({"properties": {
        "swir": {"description": "SWIR band reference or path."},
        "nir": {"description": "NIR band reference or path."}}},
        ["swir", "nir"]),
}
