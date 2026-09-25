# Knowledge retrieval: indexing, scoring, chunking

How `search_knowledge_base` works today, why it works that way, and what
changes when full texts arrive. Companion to `docs/DECISIONS.md` (D13–D17).

## 1. What is indexed

`knowledge/ncwqr_index.json`: a flat JSON array of entries. Each entry:

| Field | Meaning |
|---|---|
| `source` | Origin label: `ncwqr_maumee_export`, `ncwqr_lab_publications`, `ncwqr_derived_works`, or `analyst_synthesis` (explicitly not a publication) |
| `title` | Human title (citation for papers) |
| `identifier` | Stable id — a DOI (`doi:…`), page slug, or schema tag |
| `url` | Resolvable link (DOI URL, page URL, or empty) |
| `content` | The retrievable passage text |

Current contents (317 entries): 2 workbook-fact entries, 2 page-scope
entries, 179 lab + 133 derived full-page citation ingests
(`scripts/ingest_ncwqr.py`, re-runnable), 1 labelled synthesis. Publication
text is the verbatim citation plus year — titles/authors/DOIs exactly as the
pages carry them; no paraphrase, no asserted findings.

## 2. Chunking method (current): none — whole-entry retrieval

Each entry is already an atomic unit (one citation + topic line, or one
fact block), so the chunking step is deliberately the identity function:
one entry = one chunk. Splitting atomic citations would only dilute term
matches and break the one-entry ↔ one-reference mapping that grounding (D8)
depends on.

Truncation (not chunking): passages clip at **1200 chars** in tool hits and
**800 chars** in LLM prompts, to bound prompt size. Entries are short enough
that clipping rarely bites; lengths are worth re-checking if entries grow.

## 3. Scoring method (current): weighted keyword match

`retrieval.search_knowledge_base(query, max_hits=5)`:

1. Tokenise query with `[A-Za-z0-9]+`; lowercase; drop tokens of length ≤1.
2. Remove generic filler stopwords (`the`, `about`, `summarize`, `water`,
   `quality`, …) — **except** tokens of length ≤4, which preserves domain
   codes (`TP`, `NO23`, `CL`, `SI`).
3. Per entry, per term, over `title + content` (lowercased):
   - whole-word matches count fully, weighted **2.0** for terms longer than
     4 chars, **1.0** for short terms;
   - if no whole-word match and the term is ≤4 chars, sub-string occurrences
     count at **0.5×** (catches codes inside `Value [TP] …` style text).
4. Sum, rank descending, return top-`max_hits` with `ref` labels `S1…`,
   `relevance` scores, and the retrieval `note` (index completeness flag).

This is transparency-first: every ranking is reproducible by hand from the
rules above. Known limits: no synonyms (`phosphorus` ≠ `P`), no semantics,
English-only. Relevance-labelled evaluation (precision/recall) is future work.

## 4. Reference labelling

Hits receive call-local refs (`S1…`); the orchestrator renumbers them globally
across knowledge steps in plan order, so answer markers resolve
unambiguously. See `agent/grounding.py` for marker validation/stripping and
`citation_check` semantics.

## 5. Proposed full-text chunking (not implemented)

When PDF ingestion is justified, the intended method — recorded here so it is
reviewed *before* code, not after:

1. Source PDFs for indexed DOIs (where openly available), parsed to text with
   section structure preserved (title, abstract, methods, results, conclusion).
2. **Section-aware chunks**: split on section boundaries first; sections over
   ~1500 chars split further on paragraph boundaries with ~200-char overlap.
   Target 500–1200 chars per chunk — sized so 3–5 chunks fit a prompt
   alongside GIS summaries.
3. Each chunk stores `{doi, section, chunk_index, text}`; the index entry
   `identifier` stays the DOI, so existing grounding keeps working with
   `ref` → chunk provenance extended to section level.
4. Re-evaluate: keyword scoring first (cheap baseline, same harness), add
   embeddings only on a measured precision/recall win. Report the comparison —
   reviewers will ask why the simpler method was kept or dropped.
5. Quote-level answers: require markers to point at chunk text that entails
   the sentence (human spot-check protocol on the benchmark set before
   claiming grounded generation).
