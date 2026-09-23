"""Tool wiring shared by planner + orchestrator."""

from __future__ import annotations

from . import Tool, ToolRegistry
from .data.arcgis import (
    QUERY_ARCGIS_REQUIRED, QUERY_ARCGIS_SCHEMA, query_arcgis,
)
from .data.xlsx import (
    QUERY_MAUMEE_REQUIRED, QUERY_MAUMEE_SCHEMA, query_maumee,
)
from .gis.operations import (
    BUFFER_REQUIRED, BUFFER_SCHEMA, INTERSECT_REQUIRED, INTERSECT_SCHEMA,
    NEAREST_REQUIRED, NEAREST_SCHEMA, buffer, intersect, nearest,
)
from .knowledge.retrieval import (
    SEARCH_KB_REQUIRED, SEARCH_KB_SCHEMA, search_knowledge_base,
)
from .utility.schema import (
    DESCRIBE_DATASET_REQUIRED, DESCRIBE_DATASET_SCHEMA,
    LIST_DATASETS_REQUIRED, LIST_DATASETS_SCHEMA,
    describe_dataset, list_datasets,
)


def build_tool_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool("query_arcgis", "Retrieve GeoJSON features from a registered "
                      "ArcGIS FeatureServer dataset (semantic name).",
                      QUERY_ARCGIS_SCHEMA, query_arcgis,
                      category="data", required=QUERY_ARCGIS_REQUIRED))
    reg.register(Tool("query_maumee", "Query the local NCWQR Maumee XLSX: "
                      "records, summaries, daily means, or schema. Tabular only.",
                      QUERY_MAUMEE_SCHEMA, query_maumee,
                      category="data", required=QUERY_MAUMEE_REQUIRED))
    reg.register(Tool("buffer", "Buffer a FeatureCollection result by a distance "
                    "(CRS-aware; metres-based). Input is a $step_id reference.",
                    BUFFER_SCHEMA, buffer,
                    category="gis", required=BUFFER_REQUIRED))
    reg.register(Tool("intersect", "Features of result A intersecting result B.",
                    INTERSECT_SCHEMA, intersect,
                    category="gis", required=INTERSECT_REQUIRED))
    reg.register(Tool("nearest", "k nearest B features per A feature (km).",
                    NEAREST_SCHEMA, nearest,
                    category="gis", required=NEAREST_REQUIRED))
    reg.register(Tool("search_knowledge_base", "Keyword search over the curated "
                    "NCWQR knowledge index. Returns passages with sources.",
                    SEARCH_KB_SCHEMA, search_knowledge_base,
                    category="knowledge", required=SEARCH_KB_REQUIRED))
    reg.register(Tool("list_datasets", "List registered datasets + availability.",
                    LIST_DATASETS_SCHEMA, list_datasets,
                    category="utility", required=LIST_DATASETS_REQUIRED))
    reg.register(Tool("describe_dataset", "Live metadata for one dataset.",
                    DESCRIBE_DATASET_SCHEMA, describe_dataset,
                    category="utility", required=DESCRIBE_DATASET_REQUIRED))
    return reg
