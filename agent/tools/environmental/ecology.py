"""Ecology and biodiversity via open providers.

GBIF (no key): taxon matching plus occurrence records as point features with
taxon/year/basis fields — these compose with richness, joins, and KDE tools.
Protected areas come from OpenStreetMap (boundary=protected_area,
leisure=nature_reserve), which needs no token and stays queryable offline in
tests via the shared Overpass core.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..common import CapabilityError, ToolError, cap_int, collection, table

GBIF_URL = "https://api.gbif.org/v1"


def _gbif(path: str, params: Dict[str, Any]):
    from ..common import http_get

    resp = http_get(GBIF_URL + path, params=params, timeout=40)
    try:
        return resp.json()
    except Exception as exc:
        raise CapabilityError(f"GBIF returned non-JSON: {exc}") from exc


def gbif_match_species(name: str):
    """Match a scientific/common name to a GBIF taxon (usageKey + rank)."""
    if not isinstance(name, str) or not name.strip():
        raise ToolError("provide a species name")
    doc = _gbif("/species/match", {"name": name.strip()})
    if doc.get("matchType") in (None, "NONE"):
        return table(["name", "usageKey", "rank", "status", "matchType"], [],
                     row_count=0, note=f"no GBIF match for '{name}'")
    return table(["name", "usageKey", "rank", "status", "matchType"],
                 [{"name": doc.get("scientificName"),
                   "usageKey": doc.get("usageKey"), "rank": doc.get("rank"),
                   "status": doc.get("status"),
                   "matchType": doc.get("matchType")}])


def gbif_occurrences(taxon: str, bbox: str | None = None, limit: int = 200,
                     basis: str = ""):
    """Occurrence points for a taxon name or GBIF usageKey, optional bbox."""
    from ..common import parse_bbox

    if not isinstance(taxon, str) or not taxon.strip():
        raise ToolError("provide a taxon name or usageKey")
    taxon = taxon.strip()
    params: Dict[str, Any] = {"limit": cap_int(limit, 1, 1000, name="limit"),
                              "hasCoordinate": "true"}
    if taxon.isdigit():
        params["taxon_key"] = int(taxon)
    else:
        match = _gbif("/species/match", {"name": taxon})
        if not match.get("usageKey"):
            return collection([], note=f"no GBIF taxon for '{taxon}'")
        params["taxon_key"] = match["usageKey"]
    if basis:
        if basis.upper() not in ("OBSERVATION", "PRESERVED_SPECIMEN",
                                 "HUMAN_OBSERVATION", "MACHINE_OBSERVATION",
                                 "MATERIAL_SAMPLE"):
            raise ToolError(f"unknown basis '{basis}'")
        params["basisOfRecord"] = basis.upper()
    bounds = None
    if bbox:
        w, s, e, n = parse_bbox(bbox)
        bounds = (w, s, e, n)
        params.update({"geometry": f"POLYGON(({w} {s},{e} {s},{e} {n},"
                                   f"{w} {n},{w} {s}))"})
    doc = _gbif("/occurrence/search", params)
    feats = []
    for oc in doc.get("results", []):
        lon, lat = oc.get("decimalLongitude"), oc.get("decimalLatitude")
        if lon is None or lat is None:
            continue
        feats.append({
            "type": "Feature",
            "properties": {
                "scientificName": oc.get("scientificName"),
                "taxon_key": oc.get("taxonKey"),
                "basis": oc.get("basisOfRecord"),
                "year": oc.get("year"),
                "country": oc.get("country"),
                "gbif_id": oc.get("key"),
            },
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })
    return collection(feats, taxon=taxon,
                      taxon_key=params.get("taxon_key"),
                      bbox=list(bounds) if bounds else None,
                      total_matched=doc.get("count"))


def species_richness(input: Dict[str, Any], taxon_field: str = "scientificName"):
    """Distinct taxa + per-taxon record counts over occurrence features."""
    from ..common import valid_shapes

    pairs = valid_shapes(input)
    counts: Dict[str, int] = {}
    for feat, _ in pairs:
        taxon = (feat.get("properties", {}) or {}).get(taxon_field)
        if taxon:
            counts[str(taxon)] = counts.get(str(taxon), 0) + 1
    rows = [{"taxon": t, "records": c}
            for t, c in sorted(counts.items(), key=lambda kv: -kv[1])]
    return table(["taxon", "records"], rows, richness=len(rows),
                 records=sum(counts.values()))


def protected_area_query(bbox: str, designation: str = "",
                         max_features: int = 200):
    """Protected areas (boundary=protected_area, leisure=nature_reserve)
    from OpenStreetMap; optional designation substring filter."""
    from ..data.osm import _elements_to_features, overpass_query

    from ..common import parse_bbox

    w, s, e, n = parse_bbox(bbox)
    max_features = cap_int(max_features, 1, 1000, name="max_features")
    ql = (f"[out:json][timeout:60];(nwr({s},{w},{n},{e})"
          f'["boundary"="protected_area"];nwr({s},{w},{n},{e})'
          f'["leisure"="nature_reserve"];);out center {max_features};')
    doc = overpass_query(ql, timeout=90)
    feats = _elements_to_features(doc, False)
    if designation:
        want = designation.lower()
        feats = [f for f in feats
                 if want in str((f.get("properties", {}) or {})
                                .get("tag:protect_class", "")).lower()
                 or want in str((f.get("properties", {}) or {})
                                .get("name", "")).lower()]
    return collection(feats[:max_features], bbox=[w, s, e, n])


ECOLOGY_SCHEMAS = {
    "gbif_match_species": ({"properties": {
        "name": {"type": "string", "description": "Scientific or common name."}}},
        ["name"]),
    "gbif_occurrences": ({"properties": {
        "taxon": {"type": "string", "description": "Name or GBIF usageKey."},
        "bbox": {"type": "string", "description": "Optional spatial filter."},
        "limit": {"type": "integer"},
        "basis": {"type": "string",
                  "description": "Optional basisOfRecord filter."}}}, ["taxon"]),
    "species_richness": ({"properties": {
        "input": {"description": "Occurrence features reference."},
        "taxon_field": {"type": "string", "description": "Default 'scientificName'."}}},
        ["input"]),
    "protected_area_query": ({"properties": {
        "bbox": {"type": "string"},
        "designation": {"type": "string", "description": "Optional substring filter."},
        "max_features": {"type": "integer"}}}, ["bbox"]),
}
