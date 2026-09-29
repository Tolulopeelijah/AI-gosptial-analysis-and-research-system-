"""Knowledge-base utilities beyond raw search.

`search_publications` filters the NCWQR index by author/year/venue/DOI;
`find_related_publications` ranks by shared significant terms;
`get_dataset_provenance` reports origin/citation/coverage for a dataset;
all three reuse the same curated index (and its provenance labels) as
`search_knowledge_base`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ..common import ToolError, table
from .retrieval import _load_index

_STOP = {"the", "and", "for", "with", "from", "that", "lake", "erie", "river",
        "water", "quality", "study", "using", "based", "into"}


def _terms(text: str) -> set:
    return {t.lower() for t in re.findall(r"[A-Za-z]{4,}", text or "")
            if t.lower() not in _STOP}


def search_publications(author: str = "", year: str = "", venue: str = "",
                        doi: str = "", max_hits: int = 20):
    """Filter indexed publications by author substring, year, venue/journal
    substring, or DOI substring."""
    from ..common import cap_int

    max_hits = cap_int(max_hits, 1, 100, name="max_hits")
    hits = []
    for e in _load_index():
        if not str(e.get("identifier", "")).startswith("doi:"):
            continue
        text = f"{e.get('title', '')} {e.get('content', '')}"
        if author and author.lower() not in text.lower():
            continue
        if year and year not in text:
            continue
        if venue and venue.lower() not in text.lower():
            continue
        if doi and doi.lower() not in str(e.get("identifier", "")).lower():
            continue
        hits.append({"title": e.get("title"), "identifier": e.get("identifier"),
                     "url": e.get("url"), "source": e.get("source")})
        if len(hits) >= max_hits:
            break
    return {"ok": True, "type": "knowledge", "query": "publication filter",
            "hits": [{"ref": f"S{i}", **h} for i, h in enumerate(hits, 1)],
            "count": len(hits)}


def find_related_publications(identifier: str, max_hits: int = 5):
    """Publications sharing the most significant terms with a given DOI."""
    from ..common import cap_int

    max_hits = cap_int(max_hits, 1, 20, name="max_hits")
    entries = [e for e in _load_index()
               if str(e.get("identifier", "")).startswith("doi:")]
    seed = next((e for e in entries if e.get("identifier") == identifier), None)
    if seed is None:
        raise ToolError(f"identifier '{identifier}' not in the index; "
                        "use search_publications to browse")
    seed_terms = _terms(f"{seed.get('title', '')} {seed.get('content', '')}")
    scored = []
    for e in entries:
        if e.get("identifier") == identifier:
            continue
        overlap = seed_terms & _terms(f"{e.get('title', '')} {e.get('content', '')}")
        if overlap:
            scored.append((len(overlap), sorted(overlap)[:8], e))
    scored.sort(key=lambda t: -t[0])
    hits = [{"title": e.get("title"), "identifier": e.get("identifier"),
             "url": e.get("url"), "shared_terms": terms, "overlap": n}
            for n, terms, e in scored[:max_hits]]
    return {"ok": True, "type": "knowledge", "seed": identifier,
            "hits": [{"ref": f"S{i}", **h} for i, h in enumerate(hits, 1)],
            "count": len(hits)}


def get_dataset_provenance(dataset: str):
    """Origin, citation, coverage, and access notes for a dataset."""
    from ...registry import build_registry

    reg = build_registry()
    if dataset not in reg:
        raise ToolError(f"unknown dataset '{dataset}'")
    info = reg[dataset]
    if dataset == "maumee_water_quality":
        origin = ("Heidelberg University NCWQR tributary monitoring export; "
                  "cite DOI 10.5281/zenodo.6606949")
        coverage = "Maumee River station time-series, 1975-01-10 to 2025-09-30"
    elif info.source_type == "arcgis_feature_server":
        origin = "Lucas County ArcGIS FeatureServer layers"
        coverage = "Lucas County, Ohio"
    elif info.source_type == "user_upload":
        upload = info.extra.get("upload", {}) or {}
        origin = (f"user-uploaded file {upload.get('original_filename')}"
                  + ("; coordinates assumed EPSG:4326" if upload.get("crs_assumed") else ""))
        coverage = f"{upload.get('count')} records"
    else:
        origin, coverage = info.description, ""
    return table(["dataset", "origin", "coverage", "access_method", "available"],
                 [{"dataset": dataset, "origin": origin, "coverage": coverage,
                   "access_method": info.access_method,
                   "available": info.available}])


KNOWLEDGE_MORE_SCHEMAS = {
    "search_publications": ({"properties": {
        "author": {"type": "string", "description": "Author substring."},
        "year": {"type": "string", "description": "e.g. '2015'."},
        "venue": {"type": "string", "description": "Journal/report substring."},
        "doi": {"type": "string", "description": "DOI substring."},
        "max_hits": {"type": "integer"}}}, []),
    "find_related_publications": ({"properties": {
        "identifier": {"type": "string", "description": "Seed DOI, e.g. 'doi:...'."},
        "max_hits": {"type": "integer"}}}, ["identifier"]),
    "get_dataset_provenance": ({"properties": {
        "dataset": {"type": "string"}}}, ["dataset"]),
}
