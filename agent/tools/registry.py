"""Central tool wiring: all ~119 tools with registry metadata.

Conventions: implementation modules expose ``<AREA>_SCHEMAS`` mapping
``name -> (schema, required)`` alongside same-named functions. Each entry
below declares category, optional pip requirements beyond core, network use,
cost, input/output types, and units — powering discovery, the manifest, and
the planner's compact catalog. Existing tools keep their names, categories,
and behaviour.
"""

from __future__ import annotations

from . import Tool, ToolRegistry
from .data.arcgis import (
    QUERY_ARCGIS_REQUIRED, QUERY_ARCGIS_SCHEMA, query_arcgis,
)
from .data.datasets import DATASETS_SCHEMAS
from .data import datasets as _datasets
from .data.osm import OSM_SCHEMAS
from .data import osm as _osm
from .data.geocoding import GEOCODING_SCHEMAS
from .data import geocoding as _geocoding
from .data.boundaries import BOUNDARIES_SCHEMAS
from .data import boundaries as _boundaries
from .data.xlsx import (
    QUERY_MAUMEE_REQUIRED, QUERY_MAUMEE_SCHEMA, query_maumee,
)
from .data.uploads import (
    QUERY_USER_DATASET_REQUIRED, QUERY_USER_DATASET_SCHEMA, query_user_dataset,
)
from .geometry.construction import CONSTRUCTION_SCHEMAS
from .geometry import construction as _construction
from .geometry.vector import VECTOR_SCHEMAS
from .geometry import vector as _vector
from .geometry.relationships import RELATIONSHIP_SCHEMAS
from .geometry import relationships as _relationships
from .geometry.proximity import PROXIMITY_SCHEMAS
from .geometry import proximity as _proximity
from .geometry.measurement import MEASUREMENT_SCHEMAS
from .geometry import measurement as _measurement
from .geometry.crs import CRS_SCHEMAS
from .geometry import crs as _crs
from .gis.operations import (
    BUFFER_REQUIRED, BUFFER_SCHEMA, INTERSECT_REQUIRED, INTERSECT_SCHEMA,
    NEAREST_REQUIRED, NEAREST_SCHEMA, buffer, intersect, nearest,
)
from .analysis.joins import JOIN_SCHEMAS
from .analysis import joins as _joins
from .analysis.aggregation import AGGREGATION_SCHEMAS
from .analysis import aggregation as _aggregation
from .analysis.statistics import STATISTICS_SCHEMAS
from .analysis import statistics as _statistics
from .analysis.temporal import TEMPORAL_SCHEMAS
from .analysis import temporal as _temporal
from .network.network import NETWORK_SCHEMAS
from .network import network as _network
from .raster.raster import RASTER_SCHEMAS
from .raster import raster as _raster
from .remote_sensing.sensing import SENSING_SCHEMAS
from .remote_sensing import sensing as _sensing
from .environmental.climate import CLIMATE_SCHEMAS
from .environmental import climate as _climate
from .environmental.ecology import ECOLOGY_SCHEMAS
from .environmental import ecology as _ecology
from .visualization.maps import MAPS_SCHEMAS
from .visualization import maps as _maps
from .knowledge.retrieval import (
    SEARCH_KB_REQUIRED, SEARCH_KB_SCHEMA, search_knowledge_base,
)
from .knowledge.more import KNOWLEDGE_MORE_SCHEMAS
from .knowledge import more as _knowledge_more
from .utility.schema import (
    DESCRIBE_DATASET_REQUIRED, DESCRIBE_DATASET_SCHEMA,
    LIST_DATASETS_REQUIRED, LIST_DATASETS_SCHEMA,
    describe_dataset, list_datasets,
)
from .discovery import DISCOVERY_SCHEMAS
from . import discovery as _discovery


def _entry(registry: ToolRegistry, module, name: str, schemas: dict,
           description: str, category: str, **meta) -> None:
    schema, required = schemas[name]
    registry.register(Tool(
        name, description, schema, getattr(module, name),
        category=category, required=required,
        requires=meta.get("requires", []),
        network=meta.get("network", False),
        expensive=meta.get("expensive", False),
        input_type=meta.get("input_type", "mixed"),
        output_type=meta.get("output_type", "mixed"),
        units=meta.get("units", ""),
    ))


def _bulk(registry: ToolRegistry, module, schemas: dict, specs: dict) -> None:
    for name, (description, category, meta) in specs.items():
        _entry(registry, module, name, schemas, description, category, **meta)


GIS = {"input_type": "FeatureCollection", "output_type": "FeatureCollection"}
FC = GIS
FC_TABLE = {"input_type": "FeatureCollection", "output_type": "table"}
TABLE = {"input_type": "table", "output_type": "table"}
TABLE_ANY = {"input_type": "features-or-table", "output_type": "table"}
GEOJSON_OUT = {"output_type": "FeatureCollection"}


def build_tool_registry() -> ToolRegistry:
    reg = ToolRegistry()

    # ---- pre-existing tools (names/behaviour preserved) ----
    reg.register(Tool("query_arcgis", "Retrieve GeoJSON features from a registered "
                      "ArcGIS FeatureServer dataset (semantic name).",
                      QUERY_ARCGIS_SCHEMA, query_arcgis,
                      category="data", required=QUERY_ARCGIS_REQUIRED,
                      network=True, input_type="dataset",
                      output_type="FeatureCollection"))
    reg.register(Tool("query_maumee", "Query the local NCWQR Maumee XLSX: "
                      "records, summaries, extremes, daily means, or schema. Tabular only.",
                      QUERY_MAUMEE_SCHEMA, query_maumee,
                      category="data", required=QUERY_MAUMEE_REQUIRED,
                      input_type="dataset", output_type="table"))
    reg.register(Tool("query_user_dataset", "Retrieve features or rows from a "
                      "user-uploaded dataset by registered name (see list_datasets).",
                      QUERY_USER_DATASET_SCHEMA, query_user_dataset,
                      category="data", required=QUERY_USER_DATASET_REQUIRED,
                      input_type="dataset", output_type="mixed"))
    reg.register(Tool("buffer", "Buffer a FeatureCollection result by a distance "
                    "(CRS-aware; metres-based). Input is a $step_id reference.",
                    BUFFER_SCHEMA, buffer,
                    category="gis", required=BUFFER_REQUIRED,
                    input_type="FeatureCollection",
                    output_type="FeatureCollection", units="m"))
    reg.register(Tool("intersect", "Features of result A intersecting result B.",
                    INTERSECT_SCHEMA, intersect,
                    category="gis", required=INTERSECT_REQUIRED,
                    input_type="FeatureCollection",
                    output_type="FeatureCollection"))
    reg.register(Tool("nearest", "k nearest B features per A feature (km).",
                    NEAREST_SCHEMA, nearest,
                    category="gis", required=NEAREST_REQUIRED,
                    input_type="FeatureCollection", output_type="table",
                    units="km"))
    reg.register(Tool("search_knowledge_base", "Keyword search over the curated "
                    "NCWQR knowledge index. Returns passages with sources.",
                    SEARCH_KB_SCHEMA, search_knowledge_base,
                    category="knowledge", required=SEARCH_KB_REQUIRED,
                    input_type="text", output_type="knowledge"))
    reg.register(Tool("list_datasets", "List registered datasets + availability.",
                    LIST_DATASETS_SCHEMA, list_datasets,
                    category="utility", required=LIST_DATASETS_REQUIRED,
                    output_type="table"))
    reg.register(Tool("describe_dataset", "Live metadata for one dataset.",
                    DESCRIBE_DATASET_SCHEMA, describe_dataset,
                    category="utility", required=DESCRIBE_DATASET_REQUIRED,
                    input_type="dataset", output_type="table"))

    # ---- data discovery & access ----
    _bulk(reg, _datasets, DATASETS_SCHEMAS, {
        "search_datasets": ("Find registered datasets by keywords.",
                            "data", {"output_type": "table"}),
        "get_dataset_schema": ("Field list for a dataset (live ArcGIS discovery).",
                               "data", {"input_type": "dataset", "output_type": "table"}),
        "get_dataset_extent": ("Spatial (and Maumee temporal) extent of a dataset.",
                               "data", {"input_type": "dataset", "output_type": "table"}),
        "filter_features": ("Attribute filter (FIELD = value, >, LIKE, AND) on a result.",
                            "data", {"input_type": "FeatureCollection",
                                     "output_type": "FeatureCollection"}),
        "sample_features": ("Deterministic seeded random sample of features.",
                            "data", {"input_type": "FeatureCollection",
                                     "output_type": "FeatureCollection"}),
        "download_dataset": ("Page a whole ArcGIS layer in (capped, flagged).",
                             "data", {"network": True, "expensive": True,
                                      "input_type": "dataset",
                                      "output_type": "FeatureCollection"}),
        "query_wfs": ("WFS GetFeature as GeoJSON from any service URL.",
                      "data", {"network": True, "expensive": True,
                               "input_type": "dataset",
                               "output_type": "FeatureCollection"}),
        "wms_getmap": ("Validate layers via GetCapabilities; return a display GetMap URL.",
                       "data", {"network": True, "input_type": "dataset",
                                "output_type": "url"}),
    })
    _bulk(reg, _osm, OSM_SCHEMAS, {
        "overpass_query": ("Run raw Overpass QL (advanced).",
                           "data", {"network": True, "expensive": True,
                                    "output_type": "FeatureCollection"}),
        "query_osm_pois": ("OpenStreetMap points of interest by category + bbox.",
                           "data", {"network": True,
                                    "output_type": "FeatureCollection"}),
        "query_osm_roads": ("OpenStreetMap roads by class + bbox.",
                            "data", {"network": True,
                                     "output_type": "FeatureCollection"}),
        "query_osm_buildings": ("OpenStreetMap building footprints + bbox.",
                                "data", {"network": True,
                                         "output_type": "FeatureCollection"}),
        "query_osm_landuse": ("OpenStreetMap landuse polygons + bbox.",
                              "data", {"network": True,
                                       "output_type": "FeatureCollection"}),
        "query_osm_water": ("OpenStreetMap water bodies + bbox.",
                            "data", {"network": True,
                                     "output_type": "FeatureCollection"}),
    })
    _bulk(reg, _geocoding, GEOCODING_SCHEMAS, {
        "geocode": ("Forward-geocode a place/address to points (Nominatim).",
                    "data", {"network": True, "input_type": "text",
                             "output_type": "FeatureCollection"}),
        "reverse_geocode": ("Nearest address + admin hierarchy for coordinates.",
                            "data", {"network": True, "input_type": "coordinates",
                                     "output_type": "FeatureCollection"}),
        "resolve_location": ("Place name or 'lat, lon' pair to located features.",
                             "data", {"network": True, "input_type": "text",
                                      "output_type": "FeatureCollection"}),
    })
    _bulk(reg, _boundaries, BOUNDARIES_SCHEMAS, {
        "get_admin_boundary": ("Boundary polygon for a named country/state/county.",
                               "data", {"network": True, "input_type": "text",
                                        "output_type": "FeatureCollection"}),
        "find_containing_region": ("Admin hierarchy containing a point.",
                                   "data", {"network": True,
                                            "input_type": "coordinates",
                                            "output_type": "FeatureCollection"}),
        "get_admin_hierarchy": ("Enclosing admin levels for a place as a table.",
                                "data", {"network": True, "input_type": "text",
                                         "output_type": "table"}),
    })

    # ---- geometry ----
    _bulk(reg, _construction, CONSTRUCTION_SCHEMAS, {
        "create_point": ("Point feature from lon/lat.", "geometry",
                         {"input_type": "coordinates", **GEOJSON_OUT}),
        "create_line": ("LineString from [lon, lat] positions.", "geometry",
                        {"input_type": "coordinates", **GEOJSON_OUT}),
        "create_polygon": ("Polygon from linear rings.", "geometry",
                           {"input_type": "coordinates", **GEOJSON_OUT}),
        "create_bbox": ("Bounding-box polygon.", "geometry",
                        {"input_type": "coordinates", **GEOJSON_OUT}),
        "create_hex_grid": ("Metre-sized hexagonal tessellation over a bbox.",
                            "geometry", {"input_type": "bbox",
                                         "output_type": "FeatureCollection",
                                         "units": "m"}),
        "create_voronoi": ("Voronoi regions of point features.", "geometry",
                           {**FC}),
    })
    _bulk(reg, _vector, VECTOR_SCHEMAS, {
        "union": ("Dissolve all features into non-overlapping parts.", "geometry", FC),
        "difference": ("Parts of A not covered by B.", "geometry", FC),
        "symmetric_difference": ("Areas in exactly one of A / B.", "geometry", FC),
        "clip": ("Input features cut to a clip area.", "geometry", FC),
        "dissolve": ("Merge all features, or one per attribute value.", "geometry", FC),
        "convex_hull": ("Smallest convex polygon per feature.", "geometry", FC),
        "simplify": ("Metric Douglas-Peucker simplification with vertex report.",
                     "geometry", {**FC, "units": "m"}),
    })
    _bulk(reg, _relationships, RELATIONSHIP_SCHEMAS, {
        "within": ("A features completely inside B.", "geometry", FC),
        "contains": ("A features containing B (no boundary-only contact).",
                     "geometry", FC),
        "disjoint": ("A features sharing no point with B.", "geometry", FC),
        "covers": ("A features covering B (boundary contact allowed).",
                   "geometry", FC),
        "relate": ("DE-9IM matrix per A feature, optional pattern filter.",
                   "geometry", {"input_type": "FeatureCollection",
                                "output_type": "mixed"}),
        "spatial_filter": ("Filter A by any named predicate (plan-time choice).",
                           "geometry", FC),
    })
    _bulk(reg, _proximity, PROXIMITY_SCHEMAS, {
        "distance": ("Pairwise A×B distances in kilometres (metric).", "geometry",
                     {**FC_TABLE, "units": "km"}),
        "within_distance": ("A features within a metric distance of B.", "geometry",
                            {**FC, "units": "m"}),
        "distance_matrix": ("Full A×B kilometre matrix table.", "geometry",
                            {**FC_TABLE, "units": "km"}),
    })
    _bulk(reg, _measurement, MEASUREMENT_SCHEMAS, {
        "calculate_area": ("Polygon area per feature (sqm/sqkm).", "geometry",
                           {**FC_TABLE, "units": "m2|km2"}),
        "calculate_length": ("Line length per feature (m/km).", "geometry",
                             {**FC_TABLE, "units": "m|km"}),
        "calculate_bearing": ("Bearing in degrees clockwise from north.", "geometry",
                              {**FC_TABLE, "units": "degrees"}),
        "calculate_centroid_coords": ("Centroid lon/lat per feature.", "geometry",
                                      {**FC_TABLE, "units": "degrees"}),
        "calculate_geometry_statistics": ("Area/length/vertices/bbox per feature.",
                                          "geometry", FC_TABLE),
    })
    _bulk(reg, _crs, CRS_SCHEMAS, {
        "get_crs": ("Report a result's declared CRS.", "geometry",
                    {"input_type": "mixed", "output_type": "table"}),
        "set_crs": ("Assign (not transform) a CRS label.", "geometry",
                    {"input_type": "FeatureCollection",
                     "output_type": "FeatureCollection"}),
        "transform_crs": ("Reproject a collection to a target CRS.", "geometry",
                          {"input_type": "FeatureCollection",
                           "output_type": "FeatureCollection"}),
        "get_utm_zone": ("UTM zone + EPSG for lon/lat.", "geometry",
                         {"input_type": "coordinates", "output_type": "table"}),
        "transform_coordinates": ("Reproject raw [x, y] positions.", "geometry",
                                  {"input_type": "coordinates",
                                   "output_type": "table"}),
    })

    # ---- analysis ----
    _bulk(reg, _joins, JOIN_SCHEMAS, {
        "spatial_join": ("Attach B attributes to A by predicate.", "analysis", FC),
        "join_by_nearest": ("Attach k nearest B attributes + distance km.", "analysis",
                            {**FC, "units": "km"}),
        "aggregate_join": ("Roll B values up per A feature (count/sum/mean/min/max).",
                           "analysis", FC),
        "transfer_attributes": ("Copy named fields across a spatial match.", "analysis", FC),
    })
    _bulk(reg, _aggregation, AGGREGATION_SCHEMAS, {
        "count_features": ("Feature count + geometry-type breakdown.", "analysis",
                           {**FC_TABLE}),
        "aggregate_features": ("Single rolled-up value over a numeric field.",
                               "analysis", {"input_type": "features-or-table",
                                            "output_type": "table"}),
        "summarize_by_attribute": ("Group statistics per category.", "analysis",
                                   {"input_type": "features-or-table",
                                    "output_type": "table"}),
        "percentage_by_area": ("Share (%) of each A polygon covered by B.", "analysis",
                               {**FC_TABLE, "units": "percent"}),
    })
    _bulk(reg, _statistics, STATISTICS_SCHEMAS, {
        "calculate_mean": ("Mean of a numeric field.", "analysis", TABLE_ANY),
        "calculate_std": ("Standard deviation + variance.", "analysis", TABLE_ANY),
        "calculate_percentiles": ("Quantile cut points.", "analysis", TABLE_ANY),
        "calculate_correlation": ("Pearson r between two fields.", "analysis", TABLE_ANY),
        "moran_i": ("Global Moran's I with z-score, p-value, interpretation.",
                    "analysis", {**FC_TABLE, "requires": []}),
        "local_moran": ("LISA quadrants (HH/LL/HL/LH) per feature.", "analysis",
                        {**FC_TABLE, "requires": []}),
        "getis_ord": ("Getis-Ord G* z-score per feature.", "analysis",
                      {**FC_TABLE, "requires": []}),
        "hotspot_analysis": ("Hotspot/coldspot classification from G*.", "analysis",
                             {**FC_TABLE, "requires": []}),
        "kernel_density": ("Gaussian KDE grid cells (per km²) over points.", "analysis",
                           {**FC, "units": "per_km2", "requires": []}),
    })
    _bulk(reg, _temporal, TEMPORAL_SCHEMAS, {
        "filter_by_date": ("Rows on one calendar day.", "analysis", TABLE_ANY),
        "filter_by_time_range": ("Rows within [start, end].", "analysis", TABLE_ANY),
        "aggregate_temporal": ("Resample a field to D/W/ME/YE buckets.", "analysis",
                               TABLE_ANY),
        "temporal_statistics": ("Stats plus first/last timestamps and span.", "analysis",
                                TABLE_ANY),
        "detect_temporal_trend": ("Least-squares slope/day, R², direction.", "analysis",
                                  TABLE_ANY),
    })

    # ---- network ----
    _bulk(reg, _network, NETWORK_SCHEMAS, {
        "build_network": ("Routable metric graph from LineStrings.", "network",
                          {"input_type": "FeatureCollection",
                           "output_type": "network", "units": "m"}),
        "download_street_network": ("OSM roads for a bbox, built into a network.",
                                    "network", {"network": True, "expensive": True,
                                                "input_type": "bbox",
                                                "output_type": "network"}),
        "shortest_path": ("Dijkstra path between lon/lat points as a line.", "network",
                          {"input_type": "network", "output_type": "FeatureCollection",
                           "units": "m"}),
        "travel_time": ("Minutes over a path at a given speed.", "network",
                        {"input_type": "path", "output_type": "table",
                         "units": "minutes"}),
        "service_area": ("Reachable-nodes convex hull for a time budget.", "network",
                         {"input_type": "network", "output_type": "FeatureCollection",
                          "units": "minutes"}),
        "betweenness_centrality": ("Brandes betweenness, top nodes with lon/lat.",
                                   "network", {"expensive": True,
                                               "input_type": "network",
                                               "output_type": "table"}),
    })

    # ---- raster ----
    _bulk(reg, _raster, RASTER_SCHEMAS, {
        "load_raster": ("Open a GeoTIFF into a chainable raster descriptor.", "raster",
                        {"requires": ["rasterio"], "input_type": "path",
                         "output_type": "raster"}),
        "describe_raster": ("Metadata + per-band statistics.", "raster",
                            {"requires": ["rasterio"], "input_type": "raster",
                             "output_type": "table"}),
        "clip_raster": ("Clip to a bbox (CRS-checked).", "raster",
                        {"requires": ["rasterio"], "input_type": "raster",
                         "output_type": "raster"}),
        "resample_raster": ("Resample by scale factor + method.", "raster",
                            {"requires": ["rasterio"], "input_type": "raster",
                             "output_type": "raster"}),
        "raster_statistics": ("Per-band count/min/max/mean/std table.", "raster",
                              {"requires": ["rasterio"], "input_type": "raster",
                               "output_type": "table"}),
        "zonal_statistics": ("Per-zone stats of a raster over polygons.", "raster",
                             {"requires": ["rasterio"],
                              "input_type": "mixed", "output_type": "table"}),
        "raster_calculator": ("AST-validated band math (no raw eval).", "raster",
                              {"requires": ["rasterio"],
                               "input_type": "raster", "output_type": "raster"}),
        "raster_reclassify": ("Reclassify by 'lo-hi:value' ranges.", "raster",
                              {"requires": ["rasterio"],
                               "input_type": "raster", "output_type": "raster"}),
        "raster_slope": ("Horn's slope in degrees or percent.", "raster",
                         {"requires": ["rasterio"],
                          "input_type": "raster", "output_type": "raster",
                          "units": "degrees|percent"}),
    })

    # ---- remote sensing / environment ----
    _bulk(reg, _sensing, SENSING_SCHEMAS, {
        "stac_search": ("Find Sentinel-2/Landsat scenes with asset URLs (no key).",
                        "sensing", {"network": True, "output_type": "table"}),
        "calculate_ndvi": ("(NIR−Red)/(NIR+Red) from two band rasters.", "sensing",
                           {"requires": ["rasterio"],
                            "input_type": "raster", "output_type": "raster",
                            "units": "index_-1..1"}),
        "calculate_ndwi": ("McFeeters (Green−NIR)/(Green+NIR).", "sensing",
                           {"requires": ["rasterio"],
                            "input_type": "raster", "output_type": "raster",
                            "units": "index_-1..1"}),
        "calculate_ndbi": ("(SWIR−NIR)/(SWIR+NIR) built-up index.", "sensing",
                           {"requires": ["rasterio"],
                            "input_type": "raster", "output_type": "raster",
                            "units": "index_-1..1"}),
    })
    _bulk(reg, _climate, CLIMATE_SCHEMAS, {
        "current_weather": ("Current temp/humidity/precip/wind (Open-Meteo, no key).",
                            "environmental", {"network": True,
                                              "input_type": "coordinates",
                                              "output_type": "table"}),
        "daily_weather": ("Daily max/min temp, precip, wind for a date range.",
                          "environmental", {"network": True,
                                            "input_type": "coordinates",
                                            "output_type": "table"}),
        "climate_statistics": ("Aggregate a daily_weather table.", "environmental",
                               {"input_type": "table", "output_type": "table"}),
    })
    _bulk(reg, _ecology, ECOLOGY_SCHEMAS, {
        "gbif_match_species": ("Match a name to a GBIF taxon key.", "environmental",
                               {"network": True, "input_type": "text",
                                "output_type": "table"}),
        "gbif_occurrences": ("GBIF occurrence points for a taxon, optional bbox.",
                             "environmental", {"network": True,
                                               "output_type": "FeatureCollection"}),
        "species_richness": ("Distinct taxa + per-taxon counts.", "environmental",
                             {**FC_TABLE}),
        "protected_area_query": ("OSM protected areas + nature reserves by bbox.",
                                 "environmental", {"network": True,
                                                  "output_type": "FeatureCollection"}),
    })

    # ---- visualization ----
    _bulk(reg, _maps, MAPS_SCHEMAS, {
        "create_map_result": ("Assemble result references into named map layers.",
                              "visualization", {"input_type": "mixed",
                                                "output_type": "map_layers"}),
        "style_layer": ("Attach hex/weight/opacity/radius style override.",
                        "visualization", {**FC}),
        "export_geojson": ("Serialise features to a download payload.", "visualization",
                           {"input_type": "FeatureCollection",
                            "output_type": "download"}),
        "export_csv": ("Serialise a table (or properties) to CSV payload.", "visualization",
                       {"input_type": "mixed", "output_type": "download"}),
        "create_choropleth": ("Attach quantile/equal-interval breaks spec.", "visualization",
                              {**FC}),
    })

    # ---- knowledge ----
    _bulk(reg, _knowledge_more, KNOWLEDGE_MORE_SCHEMAS, {
        "search_publications": ("Filter indexed publications by author/year/venue/DOI.",
                                "knowledge", {"input_type": "text",
                                              "output_type": "knowledge"}),
        "find_related_publications": ("Publications sharing terms with a DOI.",
                                      "knowledge", {"input_type": "text",
                                                   "output_type": "knowledge"}),
        "get_dataset_provenance": ("Origin/citation/coverage for a dataset.",
                                   "knowledge", {"input_type": "dataset",
                                                "output_type": "table"}),
    })

    # ---- discovery ----
    _bulk(reg, _discovery, DISCOVERY_SCHEMAS, {
        "discover_tools": ("List tools, optionally by category.", "discovery",
                           {"output_type": "table"}),
        "search_tools": ("Keyword search over the tool catalogue.", "discovery",
                         {"input_type": "text", "output_type": "table"}),
        "get_tool_metadata": ("Full registry record for one tool.", "discovery",
                              {"input_type": "text", "output_type": "table"}),
    })
    return reg
