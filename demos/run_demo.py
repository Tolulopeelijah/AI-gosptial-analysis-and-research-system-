"""End-to-end demonstrations for the 5 spec queries.

Usage:  python demos/run_demo.py
Uses the rule-based planner when OPENAI_API_KEY is unset; uses the OpenAI
planner otherwise. ArcGIS-backed demos report honest 'unavailable' until the
ARCGIS_*_URL values are configured.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

from agent.agent import GeospatialAgent

QUERIES = [
    "Show septic systems in the available dataset.",
    "Find septic systems that intersect floodplain areas.",
    "Find septic systems within 2 km of floodplain areas.",
    "Find the relevant NCWQR publications about the environmental or "
    "water-quality implications related to this analysis and summarize them.",
    "Find septic systems near floodplain areas and summarize relevant NCWQR "
    "research that may help interpret the result.",
]

EXTRA = ["Summarize total phosphorus (TP) in the Maumee dataset."]


def main() -> None:
    agent = GeospatialAgent()
    print(f"Planner: {type(agent.planner).__name__}")
    for i, q in enumerate([*QUERIES, *EXTRA], 1):
        print(f"\n{'=' * 70}\nQuery {i}: {q}")
        resp = agent.ask(q)
        print(f"status={resp['status']} dataset={resp.get('dataset')} "
              f"count={resp.get('count')} timing={resp.get('timingMs')}ms")
        print("explanation:", (resp.get("explanation") or "")[:600])
        if resp.get("error"):
            print("error:", json.dumps(resp["error"])[:300])
        if resp.get("sources"):
            print("sources:", json.dumps(resp["sources"])[:400])


if __name__ == "__main__":
    main()
