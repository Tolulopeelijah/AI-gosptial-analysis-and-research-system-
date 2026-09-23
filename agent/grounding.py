"""Citation grounding: keeps knowledge answers tied to retrieved sources.

Mechanism (deliberately mechanical, not model-judged):

* Retrieval hits carry ``[S#]`` reference labels (see
  ``tools/knowledge/retrieval.py``; renumbered globally by the orchestrator).
* The explanation prompt requires every factual sentence to end with the
  ``[S#]`` marker(s) of the passage(s) supporting it, and forbids inventing
  markers or citing anything not provided.
* This module then checks the produced text: markers not present in the hit
  list are stripped (so a hallucinated citation can never render as valid),
  and a ``citation_check`` record reports what was found/removed.

What this guarantees: no *dangling* citations. What it cannot guarantee:
that a sentence marked ``[S2]`` is truly entailed by passage S2 — that needs
human review or an NLI judge (documented as future work in docs/DECISIONS.md).
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

MARKER_RE = re.compile(r"\[S(\d+)\]")


def extract_markers(text: str) -> List[str]:
    """Unique ``S#`` markers in order of first appearance."""
    seen: List[str] = []
    for m in MARKER_RE.finditer(text or ""):
        ref = f"S{m.group(1)}"
        if ref not in seen:
            seen.append(ref)
    return seen


def check_markers(text: str, valid_refs: Set[str]) -> Dict[str, List[str]]:
    """Split markers into those backed by a retrieved hit and those not."""
    markers = extract_markers(text)
    return {
        "cited": [m for m in markers if m in valid_refs],
        "invalid": [m for m in markers if m not in valid_refs],
    }


def strip_invalid_markers(text: str, valid_refs: Set[str]) -> Tuple[str, int]:
    """Remove markers with no backing hit; return (cleaned_text, removed)."""

    def keep(m: re.Match) -> str:
        return m.group(0) if f"S{m.group(1)}" in valid_refs else ""

    cleaned, n = MARKER_RE.subn(keep, text or "")
    removed = len(extract_markers(text or "")) - len(extract_markers(cleaned))
    _ = n
    return cleaned, removed


def format_sources_for_prompt(references: List[Dict[str, str]]) -> str:
    """Numbered source block pasted into the explanation prompt."""
    lines = []
    for r in references:
        lines.append(
            f"[{r['ref']}] {r.get('title', '')} ({r.get('identifier', '')}): "
            f"{r.get('passage', '')[:800]}"
        )
    return "\n".join(lines)
