"""Tool abstraction + registry.

Every tool exposed to the OpenAI model has: unique name, description, JSON
input schema, deterministic implementation, structured output. The registry
produces OpenAI function-calling definitions via :meth:`openai_definitions`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema for the "arguments" object
    func: Callable[..., Dict[str, Any]]
    category: str = "utility"  # data | gis | knowledge | utility
    required: List[str] = field(default_factory=list)

    def openai_definition(self) -> Dict[str, Any]:
        schema = dict(self.parameters)
        schema.setdefault("type", "object")
        if self.required:
            schema["additionalProperties"] = False
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": self.required,
                    "additionalProperties": False,
                },
            },
        }

    def run(self, **kwargs: Any) -> Dict[str, Any]:
        try:
            result = self.func(**kwargs)
            if not isinstance(result, dict):
                return {"ok": False, "error": f"tool {self.name} returned non-dict"}
            result.setdefault("ok", True)
            return result
        except Exception as exc:  # tools must fail structurally, never raise
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return sorted(self._tools)

    def openai_definitions(self) -> List[Dict[str, Any]]:
        return [t.openai_definition() for t in self._tools.values()]

    def run(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        tool = self.get(name)
        if tool is None:
            return {"ok": False, "error": f"unknown tool '{name}'"}
        return tool.run(**arguments)
