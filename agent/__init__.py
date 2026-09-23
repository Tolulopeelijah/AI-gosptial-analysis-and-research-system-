"""Geospatial AI agent core.

Public entry points:
  - agent.agent.GeospatialAgent : natural-language query -> final result
  - agent.orchestration.Orchestrator : validated plan -> tool execution
  - agent.planner : query understanding + structured planning
"""

from .agent import GeospatialAgent

__all__ = ["GeospatialAgent"]
