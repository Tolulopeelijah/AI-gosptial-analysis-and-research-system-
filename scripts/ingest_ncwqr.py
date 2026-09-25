"""Ingest the NCWQR publication pages into the knowledge index.

Fetches the two live pages (Lab Publications, Derived Works), extracts every
citation paragraph under each year heading, and rebuilds the publication
portion of knowledge/ncwqr_index.json. Hand-maintained entries (workbook
facts, page-scope descriptions, labelled synthesis) are preserved; previously
hand-picked publication duplicates are replaced by the parsed originals.

Entry text is verbatim page content (citation + year) — no paraphrase, no
invented findings. Run:  python scripts/ingest_ncwqr.py
"""

from __future__ import annotations

import json
import re
import sys

PAGES = [
    ("https://ncwqr.org/publications/lab-publications/", "ncwqr_lab_publications"),
    ("https://ncwqr.org/publications/derived-works/", "ncwqr_derived_works"),
]
INDEX_PATH = "knowledge/ncwqr_index.json"
SKIP_PATTERNS = ("share=", "facebook.com", "wordpress.com", "gravatar.com",
                 "concept3d.com", "google.com/maps", "heidelberg.edu")


def fetch(url: str) -> str:
    import requests

    resp = requests.get(url, timeout=40,
                        headers={"User-Agent": "geospatial-agent-ingester/1.0"})
    resp.raise_for_status()
    return resp.text


def parse_page(html: str, source: str, page_url: str):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for head in soup.find_all("h2"):
        year = head.get_text(strip=True)
        if not re.fullmatch(r"(19|20)\d{2}", year):
            continue
        for sib in head.find_next_siblings():
            if sib.name == "h2":
                break
            if sib.name not in ("p", "li"):
                continue
            text = sib.get_text(" ", strip=True)
            text = re.sub(r"\s+", " ", text)
            if len(text) < 80 or "http" not in text:
                continue
            links = [a.get("href", "") for a in sib.find_all("a", href=True)]
            links = [u for u in links
                     if u.startswith("http") and not any(s in u for s in SKIP_PATTERNS)]
            if not links:
                continue
            doi = next((u for u in links if "doi.org" in u), links[0])
            m = re.search(r"doi\.org/(.+)$", doi)
            identifier = f"doi:{m.group(1)}" if m else doi
            entries.append({
                "source": source,
                "title": text if len(text) <= 240 else text[:237] + "...",
                "identifier": identifier,
                "url": doi,
                "content": f"[{year}] {text} (Source page: {page_url})",
            })
    # Dedupe by identifier, keep page order.
    seen, unique = set(), []
    for e in entries:
        if e["identifier"] not in seen:
            seen.add(e["identifier"])
            unique.append(e)
    return unique


def main() -> None:
    with open(INDEX_PATH, encoding="utf-8") as fh:
        existing = json.load(fh)
    hand = [e for e in existing
            if e.get("source") not in ("ncwqr_lab_publications", "ncwqr_derived_works")
            or e.get("identifier", "").endswith("_page")]
    ingested = []
    for url, source in PAGES:
        html = fetch(url)
        entries = parse_page(html, source, url)
        print(f"{source}: {len(entries)} entries")
        ingested.extend(entries)
    with open(INDEX_PATH, "w", encoding="utf-8") as fh:
        json.dump(hand + ingested, fh, indent=2, ensure_ascii=False)
    print(f"index: {len(hand)} hand + {len(ingested)} ingested = "
          f"{len(hand) + len(ingested)} total -> {INDEX_PATH}")


if __name__ == "__main__":
    sys.exit(main())
