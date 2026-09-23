"""Central configuration. Everything secret or deployment-specific comes from
environment variables (see .env.example). No API keys are hardcoded."""

from __future__ import annotations

import glob
import os

from dotenv import load_dotenv

load_dotenv()


def _discover_xlsx() -> str:
    explicit = os.getenv("MAUMEE_XLSX_PATH", "").strip()
    if explicit:
        return explicit
    candidates = sorted(glob.glob("data/*.xlsx"))
    return candidates[0] if candidates else ""


class Settings:
    # The operator's .env uses OPENAI_KEY; also accept the standard name.
    OPENAI_API_KEY: str = (
        os.getenv("OPENAI_API_KEY", "").strip()
        or os.getenv("OPENAI_KEY", "").strip()
    )
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

    # ArcGIS FeatureServer layer URLs. Empty until the operator provides them;
    # tools report an honest "unavailable" error instead of inventing data.
    ARCGIS_SEPTIC_URL: str = os.getenv("ARCGIS_SEPTIC_URL", "").strip()
    ARCGIS_FLOODPLAIN_0_URL: str = os.getenv("ARCGIS_FLOODPLAIN_0_URL", "").strip()
    ARCGIS_FLOODPLAIN_4_URL: str = os.getenv("ARCGIS_FLOODPLAIN_4_URL", "").strip()

    # NCWQR knowledge-source pages (knowledge retrieval, not GIS data).
    NCWQR_PUBLICATIONS_URL: str = os.getenv("NCWQR_PUBLICATIONS_URL", "").strip()
    NCWQR_DERIVED_WORKS_URL: str = os.getenv("NCWQR_DERIVED_WORKS_URL", "").strip()

    MAUMEE_XLSX_PATH: str = _discover_xlsx()
    KNOWLEDGE_INDEX_PATH: str = os.getenv(
        "KNOWLEDGE_INDEX_PATH", "knowledge/ncwqr_index.json"
    ).strip()

    # Mock switch for the Lucas County ArcGIS layers. The live servers are
    # currently unreachable from this environment (connection timeouts), so
    # ARCGIS_USE_MOCK=true (default) serves structurally representative
    # fixtures flagged as mocked. Set to "false" to hit the live URLs above
    # with no code changes.
    ARCGIS_USE_MOCK: bool = os.getenv("ARCGIS_USE_MOCK", "true").strip().lower() in (
        "1", "true", "yes",
    )


settings = Settings()
