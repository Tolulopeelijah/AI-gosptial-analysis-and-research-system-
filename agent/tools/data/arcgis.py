"""Controlled ArcGIS FeatureServer query tool.

The model supplies *semantic* parameters (`dataset`, optional attribute /
spatial filters). This module translates them into ArcGIS REST requests.

Service metadata (geometry type, fields, CRS, capabilities) is discovered at
runtime via `?f=json` — never hardcoded. Datasets without a configured URL
report `available: False` so the agent can honestly say the capability is
missing instead of inventing data.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

TIMEOUT = 30
MAX_FEATURES = 2000  # guardrail: keep payloads out of LLM context


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


def describe_layer(url: str) -> Dict[str, Any]:
    """Fetch live service metadata for one FeatureServer layer."""
    resp = requests.get(url.rstrip("/") + "?f=json", timeout=TIMEOUT)
    resp.raise_for_status()
    meta = resp.json()
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
    }


def query_arcgis(
    dataset: str,
    where: str = "1=1",
    out_fields: str = "*",
    return_geometry: bool = True,
    max_features: int = 1000,
    bbox: Optional[str] = None,
    layer: Optional[int] = None,
) -> Dict[str, Any]:
    """Query a registered ArcGIS dataset; returns a GeoJSON FeatureCollection."""
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
    if _mock_enabled():
        from .arcgis_mock import query_mock

        return query_mock(dataset, where=where, bbox=bbox,
                          max_features=max_features)

    max_features = max(1, min(int(max_features), MAX_FEATURES))
    all_features: List[Dict[str, Any]] = []
    geometry_type = ""
    errors: List[str] = []
    for url in urls:
        try:
            params: Dict[str, Any] = {
                "where": where,
                "outFields": out_fields,
                "returnGeometry": "true" if return_geometry else "false",
                "f": "geojson",
                "resultRecordCount": max_features,
            }
            if bbox:
                try:
                    west, south, east, north = [float(x) for x in bbox.split(",")]
                except ValueError:
                    return {"ok": False, "error": f"invalid bbox '{bbox}'"}
                params.update(
                    {
                        "geometry": f"{west},{south},{east},{north}",
                        "geometryType": "esriGeometryEnvelope",
                        "inSR": 4326,
                        "spatialRel": "esriSpatialRelIntersects",
                    }
                )
            # Pagination via resultOffset where supported.
            offset = 0
            per_layer: List[Dict[str, Any]] = []
            while True:
                if offset:
                    params["resultOffset"] = offset
                resp = requests.get(
                    url.rstrip("/") + "/query", params=params, timeout=TIMEOUT
                )
                resp.raise_for_status()
                page = resp.json()
                if "error" in page:
                    raise RuntimeError(page["error"])
                feats = page.get("features", [])
                per_layer.extend(feats)
                if not page.get("exceededTransferLimit") or len(per_layer) >= max_features:
                    break
                offset += len(feats)
                if offset >= max_features:
                    break
            try:
                meta = describe_layer(url)
                geometry_type = geometry_type or meta.get("geometryType", "")
            except Exception as exc:  # metadata is best-effort
                log.warning("layer metadata fetch failed for %s: %s", url, exc)
            all_features.extend(per_layer[:max_features])
            if len(all_features) >= max_features:
                break
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    if not all_features and errors:
        return {"ok": False, "error": "; ".join(errors), "code": "data_unavailable"}

    return {
        "ok": True,
        "type": "FeatureCollection",
        "features": all_features[:max_features],
        "count": len(all_features[:max_features]),
        "dataset": dataset,
        "geometry_type": geometry_type,
        "truncated": len(all_features) >= max_features,
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
            "description": "Max features to return (default 1000, cap 2000).",
        },
        "bbox": {
            "type": "string",
            "description": "Optional 'west,south,east,north' (EPSG:4326) spatial filter.",
        },
    }
}
QUERY_ARCGIS_REQUIRED = ["dataset"]
