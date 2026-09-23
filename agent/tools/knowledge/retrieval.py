"""Evidence-driven knowledge retrieval (NOT a vector DB by default).

Status: both NCWQR pages (Lab Publications, Derived Works) were fetched and
are accessible. The index (`knowledge/ncwqr_index.json`) holds page-scope
entries plus individually indexed publications directly relevant to this
project (Maumee nutrients, phosphorus sources/attribution, floods and loads)
— each transcribed from the live pages with DOI identifiers. Topic summaries
are paraphrased strictly from paper titles; no findings are asserted beyond
what the citation states. Full-text PDF ingestion is NOT implemented (that
would be the next evidence-driven step if citation-level retrieval proves
insufficient).

Every hit carries source/title/identifier/url so final answers can cite it.
`_load_index` remains the seam for future chunk ingestion.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

_INDEX_CACHE: List[Dict[str, Any]] | None = None


def _index_path() -> str:
    from ...config import settings

    return settings.KNOWLEDGE_INDEX_PATH


def _load_index() -> List[Dict[str, Any]]:
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    path = _index_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            _INDEX_CACHE = json.load(fh)
    else:
        _INDEX_CACHE = []
    return _INDEX_CACHE


def _score(text: str, terms: List[str]) -> float:
    text = text.lower()
    score = 0.0
    for term in terms:
        count = len(re.findall(r"\b" + re.escape(term) + r"\b", text))
        # sub-word fallback for short codes like "TP", "NO23"
        if count == 0 and len(term) <= 4:
            count = text.count(term) * 0.5
        score += count * (2.0 if len(term) > 4 else 1.0)
    return score


def search_knowledge_base(query: str, max_hits: int = 5) -> Dict[str, Any]:
    """Keyword search over the curated NCWQR knowledge index."""
    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) > 1]
    stop = {"the", "and", "for", "with", "what", "about", "does", "are",
            "from", "that", "this", "have", "has", "were", "related", "says",
            "find", "show", "tell", "summarize", "relevant", "water", "quality"}
    # keep domain codes even if short; drop generic filler
    terms = [t for t in terms if t not in stop or len(t) <= 4]
    # 'water quality' is the whole corpus topic; keep it from scoring
    terms = [t for t in terms if t not in {"water", "quality"}] or terms

    scored = []
    for entry in _load_index():
        hay = f"{entry.get('title', '')} {entry.get('content', '')}"
        s = _score(hay, terms)
        if s > 0:
            scored.append((s, entry))
    scored.sort(key=lambda p: -p[0])
    hits = []
    for i, (s, e) in enumerate(scored[: max(1, max_hits)], 1):
        hits.append({
            # `ref` is a call-local label (S1, S2, ...). The orchestrator
            # renumbers refs globally when several knowledge steps run, so
            # final answers never contain colliding labels.
            "ref": f"S{i}",
            "source": e.get("source"),
            "title": e.get("title"),
            "identifier": e.get("identifier"),
            "url": e.get("url"),
            "passage": e.get("content", "")[:1200],
            "relevance": round(s, 2),
        })
    from ...config import settings

    return {
        "ok": True,
        "type": "knowledge",
        "query": query,
        "hits": hits,
        "count": len(hits),
        "index_size": len(_load_index()),
        "full_text_available": bool(
            settings.NCWQR_PUBLICATIONS_URL or settings.NCWQR_DERIVED_WORKS_URL
        ),
        "note": (
            "Citation-level index from the live NCWQR pages (page scope + "
            "selected relevant publications with DOIs). Full-text PDF "
            "ingestion not implemented."
            if settings.NCWQR_PUBLICATIONS_URL
            else "Curated index only (verified dataset metadata + station "
            "context). Publication pages not yet configured."
        ),
    }


SEARCH_KB_SCHEMA = {
    "properties": {
        "query": {
            "type": "string",
            "description": "Natural-language knowledge question, e.g. phosphorus implications.",
        },
        "max_hits": {
            "type": "integer",
            "description": "Max passages to return (default 5).",
        },
    }
}
SEARCH_KB_REQUIRED = ["query"]
