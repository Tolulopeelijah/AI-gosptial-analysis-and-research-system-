"""The agent loop: understand -> decompose -> validate -> orchestrate."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from .orchestration import Orchestrator
from .planner import make_planner
from .results import ResultStore, build_final_response, new_query_id
from .tools.registry import build_tool_registry

EventSink = Optional[Callable[[Dict[str, Any]], None]]

log = logging.getLogger(__name__)

# Query modes. Research runs the full plan→execute pipeline and produces a
# paper-style report; spatial runs the same pipeline but skips the paper and
# LLM explanation (the map is the primary output); data skips the LLM analysis
# rewrite and returns raw tables/layers for download; chat adds conversation
# history to planning and explanation for follow-up questions.
MODES = ("chat", "research", "spatial", "data")


class GeospatialAgent:
    def __init__(self):
        self.tools = build_tool_registry()
        self.orchestrator = Orchestrator(self.tools)
        self.planner = make_planner()

    def ask(self, query: str, *, mode: str = "research",
            history: Optional[List[Dict[str, str]]] = None,
            aims: str = "",
            on_event: EventSink = None) -> Dict[str, Any]:
        """Run a natural-language query end to end."""
        t0 = time.time()
        query_id = new_query_id()
        if mode not in MODES:
            mode = "research"
        history = [h for h in (history or [])
                   if isinstance(h, dict) and h.get("content")][-6:]

        def emit(event: Dict[str, Any]) -> None:
            if on_event:
                on_event(event)

        emit({"type": "query_received", "queryId": query_id})
        if not query or not query.strip():
            return build_final_response(
                query_id=query_id, status="failed",
                error={"code": "invalid_geographic_query",
                       "message": "Empty query.",
                       "hint": "Ask about septic systems, floodplains, Maumee water quality, or NCWQR research."},
                timing_ms=int((time.time() - t0) * 1000))

        emit({"type": "planning", "message": "Understanding query and building execution plan."})
        outcome = self.planner.plan(query.strip(), history=history)
        plan = outcome.get("plan")
        if plan is None:
            emit({"type": "error", "code": "invalid_geographic_query",
                  "message": outcome.get("reason", "Unsupported query.")})
            return build_final_response(
                query_id=query_id, status="failed",
                explanation=outcome.get("reason", ""),
                error={"code": "invalid_geographic_query",
                       "message": outcome.get("reason", "Unsupported query."),
                       "hint": "Available: septic/floodplain GIS, Maumee water-quality summaries, NCWQR knowledge search."},
                execution={"planner": type(self.planner).__name__,
                           "kind": outcome.get("kind")},
                timing_ms=int((time.time() - t0) * 1000))

        emit({"type": "planning", "message": f"Plan ready: {len(plan.steps)} step(s).",
              "tasks": [s.id for s in plan.steps],
              "plan": [{"id": s.id, "tool": s.tool, "label": s.id} for s in plan.steps]})
        # Re-validate at the agent boundary (defence in depth).
        from .plans import validate_plan
        from .planner import _ref_consuming_tools
        from .registry import build_registry

        validate_plan(plan, known_tools=set(self.tools.names()),
                      known_datasets=set(build_registry()),
                      gis_result_tools=_ref_consuming_tools())
        response = self.orchestrator.execute(plan, query_id=query_id, on_event=on_event)
        response["timingMs"] = int((time.time() - t0) * 1000)
        response.setdefault("execution", {})["mode"] = mode
        if aims:
            response["execution"]["aims"] = aims

        # Research mode produces a paper-style report (abstract, aims,
        # methods, results, discussion, conclusion, references) alongside the
        # standard result. Deterministic sections derive from the validated
        # plan and execution record; only abstract/discussion/conclusion use
        # one grounded LLM call (with offline fallback).
        # Spatial mode skips the paper — the map is the primary output.
        if mode == "research" and response.get("status") == "completed":
            from .paper import build_paper

            try:
                response["paper"] = build_paper(query, aims, plan, response)
                emit({"type": "paper", "paper": response["paper"]})
            except Exception as exc:
                log.warning("paper build failed: %s", exc)

        # Optional LLM-written explanation pass.
        # - knowledge/combined answers always get a grounded rewrite (all
        #   modes except data/spatial);
        # - pure-GIS answers already have a professional plain-language
        #   summary from the orchestrator, but chat mode gets an LLM polish
        #   pass when a model is configured (offline fallback stays
        #   professional, so chat never sees the old "Goal: ... [..]" dump).
        # Skipped in data mode (raw results for download) and spatial mode
        # (map-first: the map is the answer, not text).
        kind = outcome.get("kind", "gis")
        if (mode == "chat" and kind == "gis"
                and response.get("status") == "completed"
                and mode not in ("data", "spatial")):
            chat_rewrite = self._chat_rewrite_with_llm(
                query, response.get("explanation", ""), response,
                history=history)
            if chat_rewrite:
                response["explanation"] = chat_rewrite
        if (mode not in ("data", "spatial") and kind in ("knowledge", "combined")
                and response.get("status") == "completed"):
            references = response.get("references") or []
            prompt_refs = [r for r in references if r.get("passage")]
            for i, t in enumerate(response.get("tables") or [], 1):
                prompt_refs.append({
                    "ref": f"T{i}",
                    "title": f"Table: {t.get('title')}",
                    "identifier": t.get("dataset", ""),
                    "passage": (
                        f"columns={t.get('columns')}; "
                        f"rows={json.dumps(t.get('rows', [])[:8])}; "
                        f"total rows={t.get('row_count')}"),
                })
            # Nothing to ground on (pure-GIS plan mislabelled, or knowledge
            # search returned zero hits): skip the rewrite so the
            # orchestrator's deterministic summary survives. Calling the LLM
            # with zero sources can only produce the "do not contain"
            # fallback, clobbering good GIS results (count/layers intact,
            # explanation destroyed).
            if not prompt_refs:
                emit({"type": "completed",
                      "explanation": response.get("explanation"),
                      "dataset": response.get("dataset"),
                      "count": response.get("count")})
                return response
            llm_text = self._explain_with_llm(
                query, response.get("explanation", ""), prompt_refs,
                history=history if mode == "chat" else None)
            _FALLBACK = "the indexed sources do not contain this information"
            if llm_text and _FALLBACK in llm_text.strip().lower():
                # Knowledge fallback must never erase GIS layers/tables.
                # Keep the deterministic draft; still record the check below.
                llm_text = ""
            if llm_text:
                response["explanation"] = llm_text
                # The rewrite must not drop the mock-data honesty note.
                mocked = (response.get("execution") or {}).get("mocked_datasets") or []
                if mocked and "demo" not in response["explanation"].lower():
                    response["explanation"] += (
                        " Note: the county map servers were unreachable, "
                        "so the results presented are demonstration data, "
                        "not official county records."
                    )
            # Grounding enforcement: strip hallucinated citations, record check.
            from .grounding import check_markers, strip_invalid_markers

            valid_refs = {r["ref"] for r in references if r.get("ref")}
            cleaned, removed = strip_invalid_markers(
                response.get("explanation", ""), valid_refs)
            response["explanation"] = cleaned
            check = check_markers(cleaned, valid_refs)
            response.setdefault("execution", {})["citation_check"] = {
                "valid_refs": sorted(valid_refs),
                "markers_found": check["cited"] + check["invalid"],
                "cited": check["cited"],
                "invalid_markers": check["invalid"],
                "stripped": removed,
            }

        emit({"type": "completed", "explanation": response.get("explanation"),
              "dataset": response.get("dataset"), "count": response.get("count")})
        return response

    # ------------------------------------------------------------- helpers ---

    def _explain_with_llm(self, query: str, draft: str,
                            references: list,
                            history: Optional[List[Dict[str, str]]] = None,
                            ) -> Optional[str]:
        from .config import settings

        if not settings.OPENAI_API_KEY:
            return None
        try:
            from openai import OpenAI

            from .grounding import format_sources_for_prompt

            messages = [
                {"role": "system",
                     "content": (
                         "Answer the question using ONLY the provided sources. "
                         "Draft findings and [T#] table sources are deterministic "
                         "tool outputs — treat their numbers and dates as ground "
                         "truth and cite them with [T#] markers. "
                         "RULES (strict):\n"
                         "1. Every sentence containing a factual claim must end "
                         "with the marker(s) of its supporting source, e.g. [S1], [T1], or [S2][T1].\n"
                         "2. Use ONLY markers from the source list (S#/T#). "
                         "Never invent markers or cite anything not listed.\n"
                         "3. If NEITHER the sources NOR the draft findings contain "
                         "the answer, say: "
                         "'The indexed sources do not contain this information.' "
                         "Do not fill the gap from general knowledge.\n"
                         "4. Do not invent publications, data, or numbers."
                     )},
            ]
            if history:
                messages.append({
                    "role": "user",
                    "content": "Conversation so far (for follow-up context):\n" + "\n".join(
                        f"{'User' if h.get('role') == 'user' else 'Assistant'}: "
                        f"{h.get('content', '')[:600]}" for h in history),
                })
            messages.append({
                "role": "user",
                "content": f"Question: {query}\nDraft findings: {draft}\n"
                f"Sources:\n{format_sources_for_prompt(references)}",
            })
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                max_tokens=500,
            )
            return resp.choices[0].message.content
        except Exception:
            return None

    def _chat_rewrite_with_llm(self, query: str, draft: str,
                               response: Dict[str, Any],
                               history: Optional[List[Dict[str, str]]] = None,
                               ) -> Optional[str]:
        """Professional polish for chat-mode GIS answers.

        The draft is already factual (deterministic counts from the
        orchestrator); this pass restates it in a professional,
        plain-language tone for a non-technical audience. Numbers, dataset
        names and honesty notes must be kept — never invented. Returns None
        offline / on failure so the deterministic draft survives.
        """
        from .config import settings

        if not settings.OPENAI_API_KEY:
            return None
        if not draft:
            return None
        try:
            from openai import OpenAI

            layers = response.get("results") or []
            # Mark the answer layer explicitly so the rewrite can't crown a
            # context layer (e.g. "2 floodplain areas" when the answer is the
            # septic systems found near them).
            layer_bits = "; ".join(
                f"{'ANSWER' if (l.get('metadata') or {}).get('role') == 'primary' else 'context'} "
                f"{(l.get('metadata') or {}).get('title')}: "
                f"{(l.get('metadata') or {}).get('count')} features "
                f"({(l.get('metadata') or {}).get('dataset')})"
                for l in layers[:5])
            mocked = ((response.get("execution") or {}).get("mocked_datasets")
                      or [])
            messages = [
                {"role": "system",
                 "content": (
                      "Restate the draft GIS result in a professional, "
                      "plain-language tone for a non-technical audience "
                      "(2-4 sentences, neutral and factual, no slang, "
                      "no first-person chat). "
                      "The layer marked ANSWER is the result to report; "
                      "context layers were only searched against. "
                      "Keep every number, place/dataset name and honesty note "
                      "exactly — do not invent data, locations, or counts. "
                     "Never output debug text: no 'Goal:', no bracketed "
                     "dumps like '[layer trouble: ...]' or '[per-layer ...]', "
                     "no 'Sources: a; b', no step ids, no raw URLs. "
                     "If the result is empty, state that no matching "
                     "records were found and suggest refining the area. "
                     "If demo data was used, keep one plain sentence: "
                     "the county map servers were unreachable so the results "
                     "are demonstration data, not official county records."
                 )},
            ]
            if history:
                messages.append({
                    "role": "user",
                    "content": "Conversation so far (for follow-up context):\n" + "\n".join(
                        f"{'User' if h.get('role') == 'user' else 'Assistant'}: "
                        f"{h.get('content', '')[:600]}" for h in history[-4:]),
                })
            messages.append({
                "role": "user",
                "content": f"User asked: {query}\nDraft result: {draft}\n"
                           f"Layers: {layer_bits}\n"
                           f"Demo datasets: {', '.join(mocked) or 'none'}",
            })
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                max_tokens=300,
            )
            text = (resp.choices[0].message.content or "").strip()
            # Paranoia: an LLM that echoes debug formatting defeats the fix —
            # fall back to the deterministic draft instead.
            if any(marker in text for marker in (
                    "Goal:", "layer trouble:", "per-layer ", "Sources:")):
                return None
            return text or None
        except Exception:
            return None

    def answer_stream(self, query: str, *, mode: str = "research",
                      history: Optional[List[Dict[str, str]]] = None,
                      aims: str = "") -> Dict[str, Any]:
        """Non-streaming response plus the event log (for the HTTP layer)."""
        events: List[Dict[str, Any]] = []
        response = self.ask(query, mode=mode, history=history, aims=aims,
                            on_event=events.append)
        response["events"] = events
        return response
