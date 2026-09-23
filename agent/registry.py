"""Semantic dataset registry.

The agent reasons about *semantic* names ("septic_systems", "floodplains",
"maumee_water_quality"). Access details (ArcGIS URLs, file paths) live here,
populated from environment / runtime discovery — never invented.

ArcGIS entries are completed at runtime by querying the service metadata
endpoints (`?f=json`): geometry type, fields, CRS and capabilities come from
the service itself. Until ARCGIS_*_URL values are configured, those datasets
are registered as `available=False` so the planner reports an honest
limitation instead of hallucinating data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import settings


@dataclass
class DatasetInfo:
    name: str
    description: str
    source_type: str  # "arcgis_feature_server" | "local_xlsx"
    access_method: str  # tool name that can read it
    geometry_type: Optional[str] = None
    crs: Optional[str] = None
    fields: List[str] = field(default_factory=list)
    url: Optional[str] = None
    available: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source_type": self.source_type,
            "access_method": self.access_method,
            "geometry_type": self.geometry_type,
            "crs": self.crs,
            "fields": self.fields,
            "available": self.available,
            "extra": self.extra,
        }


# --- Maumee XLSX schema: verified by inspecting the actual workbook ------
# Workbook sheets: ["ReadMe", "Maumee_samples"].
# Maumee_samples: 22,753 rows, 1975-01-10 -> 2025-09-30, one DateTime column
# plus 10 water-quality parameters, each as (Qualifiers, Value) pairs.
# It is station-level time-series observations: NO per-row coordinates.
MAUMEE_PARAMETERS = [
    {"code": "FLOW", "label": "Flow (cfs)"},
    {"code": "TSS", "label": "Total Suspended Solids (mg/L)"},
    {"code": "TP", "label": "Total Phosphorus (mg-P/L)"},
    {"code": "SRP", "label": "Soluble Reactive Phosphorus (mg-P/L)"},
    {"code": "NO23", "label": "Nitrite + Nitrate (mg-N/L)"},
    {"code": "TKN", "label": "Total Kjeldahl Nitrogen (mg-N/L)"},
    {"code": "CL", "label": "Chloride (mg/L)"},
    {"code": "SO4", "label": "Sulfate (mg/L)"},
    {"code": "SI", "label": "Total Silica (mg-Si/L)"},
    {"code": "COND", "label": "Conductivity (umho)"},
]
MAUMEE_COLUMNS = ["DateTime"] + [
    f"{kind} [{p['code']}] {p['label']}"
    for p in MAUMEE_PARAMETERS
    for kind in ("Qualifiers", "Value")
]


def build_registry() -> Dict[str, DatasetInfo]:
    xlsx_ok = bool(settings.MAUMEE_XLSX_PATH)
    mock = settings.ARCGIS_USE_MOCK
    flood_urls = [u for u in (settings.ARCGIS_FLOODPLAIN_0_URL,
                              settings.ARCGIS_FLOODPLAIN_4_URL) if u]
    registry = {
        "septic_systems": DatasetInfo(
            name="septic_systems",
            description=(
                "Septic system geographic features (LCHD layer)"
                + (" [MOCK-BACKED: fixture points, provisional schema]" if mock else "")
            ),
            source_type="arcgis_feature_server",
            access_method="query_arcgis",
            geometry_type="Point (provisional, mock)" if mock else None,
            crs="EPSG:4326 (provisional, mock)" if mock else None,
            fields=["OBJECTID", "STATUS (provisional)"] if mock else [],
            url=settings.ARCGIS_SEPTIC_URL or None,
            available=bool(settings.ARCGIS_SEPTIC_URL) or mock,
            extra={"mock_backed": mock,
                   "live_urls": [settings.ARCGIS_SEPTIC_URL] if settings.ARCGIS_SEPTIC_URL else []},
        ),
        "floodplains": DatasetInfo(
            name="floodplains",
            description=(
                "Floodplain polygons (Floodplain layers 0 and 4)"
                + (" [MOCK-BACKED: fixture polygons, provisional schema]" if mock else "")
            ),
            source_type="arcgis_feature_server",
            access_method="query_arcgis",
            geometry_type="Polygon (provisional, mock)" if mock else None,
            crs="EPSG:4326 (provisional, mock)" if mock else None,
            fields=["OBJECTID", "ZONE (provisional)"] if mock else [],
            url=settings.ARCGIS_FLOODPLAIN_0_URL or None,
            available=bool(flood_urls) or mock,
            extra={"mock_backed": mock, "live_urls": flood_urls,
                   **({"layer4_url": settings.ARCGIS_FLOODPLAIN_4_URL}
                      if settings.ARCGIS_FLOODPLAIN_4_URL else {})},
        ),
        "maumee_water_quality": DatasetInfo(
            name="maumee_water_quality",
            description=(
                "NCWQR Maumee River station time-series water-quality "
                "observations (1975-present): flow, suspended solids, "
                "phosphorus species, nitrogen species, chloride, sulfate, "
                "silica, conductivity. Tabular, station-level, no per-row "
                "coordinates."
            ),
            source_type="local_xlsx",
            access_method="query_maumee",
            geometry_type=None,
            crs=None,
            fields=list(MAUMEE_COLUMNS),
            available=xlsx_ok,
            extra={
                "path": settings.MAUMEE_XLSX_PATH,
                "sheet": "Maumee_samples",
                "parameters": [p["code"] for p in MAUMEE_PARAMETERS],
                "grain": "station time-series (no per-row geometry)",
            },
        ),
    }
    return registry


def available_datasets(registry: Dict[str, DatasetInfo]) -> List[str]:
    return [name for name, ds in registry.items() if ds.available]
