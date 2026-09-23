"""The agent loop: understand -> decompose -> validate -> orchestrate."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from .orchestration import Orchestrator
from .planner import make_planner
from .results import ResultStore, build_final_response, new_query_id
from .tools.registry import build_tool_registry

EventSink = Optional[Callable[[Dict[str, Any]], None]]


class GeospatialAgent:
    def __init__(self):
        self.tools = build_tool_registry()
        self.orchestrator = Orchestrator(self.tools)
        self.planner = make_planner()

    def ask(self, query: str, *, on_event: EventSink = None) -> Dict[str, Any]:
        """Run a natural-language query end to end."""
        t0 = time.time()
        query_id = new_query_id()

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
        outcome = self.planner.plan(query.strip())
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
        from .planner import GIS_RESULT_TOOLS
        from .registry import build_registry

        validate_plan(plan, known_tools=set(self.tools.names()),
                      known_datasets=set(build_registry()),
                      gis_result_tools=GIS_RESULT_TOOLS)
        response = self.orchestrator.execute(plan, query_id=query_id, on_event=on_event)
        response["timingMs"] = int((time.time() - t0) * 1000)

        # Optional LLM-written explanation pass (only for knowledge/combined
        # answers; GIS summaries already come from the orchestrator).
        kind = outcome.get("kind", "gis")
        if kind in ("knowledge", "combined") and response.get("status") == "completed":
            references = response.get("references") or []
            llm_text = self._explain_with_llm(
                query, response.get("explanation", ""), references)
            if llm_text:
                response["explanation"] = llm_text
                # The rewrite must not drop the mock-data honesty note.
                mocked = (response.get("execution") or {}).get("mocked_datasets") or []
                if mocked and "mock-backed" not in response["explanation"]:
                    response["explanation"] += (
                        " Note: " + ", ".join(mocked) + " feature(s) are "
                        "mock-backed fixtures (live ArcGIS servers "
                        "unreachable); geometry and attributes are "
                        "provisional, not real county records."
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
                            references: list) -> Optional[str]:
        from .config import settings

        if not settings.OPENAI_API_KEY:
            return None
        try:
            from openai import OpenAI

            from .grounding import format_sources_for_prompt

            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system",
                     "content": (
                         "Answer the question using ONLY the provided sources. "
                         "RULES (strict):\n"
                         "1. Every sentence containing a factual claim must end "
                         "with the marker(s) of its supporting source, e.g. [S1] or [S2][S3].\n"
                         "2. Use ONLY markers from the source list (S1..Sn). "
                         "Never invent markers or cite anything not listed.\n"
                         "3. If the sources do not contain the answer, say: "
                         "'The indexed sources do not contain this information.' "
                         "Do not fill the gap from general knowledge.\n"
                         "4. Do not invent publications, data, or numbers."
                     )},
                    {"role": "user",
                     "content": f"Question: {query}\nDraft findings: {draft}\n"
                     f"Sources:\n{format_sources_for_prompt(references)}"},
                ],
                max_tokens=500,
            )
            return resp.choices[0].message.content
        except Exception:
            return None

    def answer_stream(self, query: str) -> Dict[str, Any]:
        """Non-streaming response plus the event log (for the HTTP layer)."""
        events: List[Dict[str, Any]] = []
        response = self.ask(query, on_event=events.append)
        response["events"] = events
        return response
