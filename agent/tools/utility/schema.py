"""Utility tools: dataset discovery for the model."""

from __future__ import annotations

from typing import Any, Dict


def list_datasets() -> Dict[str, Any]:
    """List registered datasets with availability flags."""
    from ...registry import available_datasets, build_registry

    reg = build_registry()
    return {
        "ok": True,
        "datasets": [ds.to_dict() for ds in reg.values()],
        "available": available_datasets(reg),
    }


def describe_dataset(dataset: str) -> Dict[str, Any]:
    """Live metadata for one dataset (ArcGIS discovery or XLSX schema)."""
    from ...registry import build_registry

    reg = build_registry()
    if dataset not in reg:
        return {
            "ok": False,
            "error": f"unknown dataset '{dataset}'; known: {sorted(reg)}",
        }
    info = reg[dataset]
    out = info.to_dict()
    if info.source_type == "arcgis_feature_server":
        from ...config import settings as _settings

        if _settings.ARCGIS_USE_MOCK:
            from ..data.arcgis_mock import describe_mock

            meta = describe_mock(dataset)
            out["layers"] = [meta]
            out["geometry_type"] = meta.get("geometryType")
            out["crs"] = meta.get("spatialReference")
            out["fields"] = meta.get("field_names", [])
            return {"ok": True, "dataset": out}
        if info.url:
            from ..data.arcgis import describe_layer, _layer_urls

            try:
                layers = []
                for url in _layer_urls(dataset, info.extra):
                    layers.append({**describe_layer(url), "url": url})
                out["layers"] = layers
                if layers:
                    out["geometry_type"] = layers[0].get("geometryType")
                    out["crs"] = layers[0].get("spatialReference")
                    out["fields"] = layers[0].get("field_names", [])
            except Exception as exc:
                out["metadata_error"] = str(exc)
    return {"ok": True, "dataset": out}


LIST_DATASETS_SCHEMA = {"properties": {}}
LIST_DATASETS_REQUIRED = []
DESCRIBE_DATASET_SCHEMA = {
    "properties": {
        "dataset": {"type": "string", "description": "Semantic dataset name."}
    }
}
DESCRIBE_DATASET_REQUIRED = ["dataset"]
