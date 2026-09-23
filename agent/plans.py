"""Typed execution-plan schema + validation.

The LLM proposes a plan; nothing executes until :func:`validate_plan`
accepts it. Unknown tools, unknown datasets, dangling dependencies and
dependency cycles are rejected here, not at execution time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class PlanStep(BaseModel):
    id: str = Field(..., min_length=1)
    tool: str = Field(..., min_length=1)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    goal: str = Field(..., min_length=1)
    steps: List[PlanStep] = Field(..., min_length=1)

    @field_validator("steps")
    @classmethod
    def _unique_ids(cls, steps: List[PlanStep]) -> List[PlanStep]:
        ids = [s.id for s in steps]
        if len(set(ids)) != len(ids):
            raise ValueError("plan step ids must be unique")
        return steps


class PlanValidationError(ValueError):
    pass


def validate_plan(
    plan: ExecutionPlan,
    *,
    known_tools: set[str],
    known_datasets: Optional[set[str]] = None,
    gis_result_tools: Optional[set[str]] = None,
) -> ExecutionPlan:
    """Validate tool names, dataset references, dependencies and acyclicity."""
    known_datasets = known_datasets or set()
    gis_result_tools = gis_result_tools or set()

    by_id = {s.id: s for s in plan.steps}
    for step in plan.steps:
        if step.tool not in known_tools:
            raise PlanValidationError(
                f"step '{step.id}' uses unknown tool '{step.tool}'"
            )
        for dep in step.depends_on:
            if dep not in by_id:
                raise PlanValidationError(
                    f"step '{step.id}' depends on unknown step '{dep}'"
                )
        dataset = step.arguments.get("dataset")
        if (
            dataset is not None
            and step.tool in {"query_arcgis", "query_maumee", "describe_dataset"}
            and dataset not in known_datasets
        ):
            raise PlanValidationError(
                f"step '{step.id}' references unknown dataset '{dataset}'"
            )
        # GIS ops consume prior results via $ref-style references; a bare GIS
        # step with no dependency is almost certainly a malformed plan.
        if step.tool in gis_result_tools and not step.depends_on:
            inputs = [
                v
                for v in step.arguments.values()
                if isinstance(v, str) and v.startswith("$")
            ]
            if not inputs:
                raise PlanValidationError(
                    f"step '{step.id}' ({step.tool}) has no input result "
                    "reference and no dependencies"
                )

    # Cycle detection (Kahn's algorithm).
    indegree = {s.id: len(s.depends_on) for s in plan.steps}
    dependents: Dict[str, List[str]] = {s.id: [] for s in plan.steps}
    for step in plan.steps:
        for dep in step.depends_on:
            dependents[dep].append(step.id)
    queue = [sid for sid, deg in indegree.items() if deg == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for nxt in dependents[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited != len(plan.steps):
        raise PlanValidationError("plan contains a dependency cycle")

    return plan


def topo_order(plan: ExecutionPlan) -> List[List[PlanStep]]:
    """Group steps into dependency levels (each level may run in parallel)."""
    done: set[str] = set()
    remaining = list(plan.steps)
    levels: List[List[PlanStep]] = []
    while remaining:
        ready = [s for s in remaining if all(d in done for d in s.depends_on)]
        if not ready:
            raise PlanValidationError("plan has unsatisfiable dependencies")
        levels.append(ready)
        for s in ready:
            done.add(s.id)
        remaining = [s for s in remaining if s.id not in done]
    return levels


PlanKind = Literal["gis", "knowledge", "combined", "unsupported"]
