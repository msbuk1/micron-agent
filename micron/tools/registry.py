"""Tool registry — manages tool registration and execution."""
import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    func: Callable
    description: str
    parameters: dict
    write: bool


class ToolRegistry:
    """Registry for agent tools with OpenAI-compatible schemas."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        func: Callable,
        description: str,
        parameters: dict,
        write: bool = False,
    ):
        """Register a tool function."""
        # Ensure parameters is a valid JSON schema
        if "type" not in parameters:
            parameters = {"type": "object", "properties": parameters}
        if "required" not in parameters:
            # Auto-detect required from function signature
            sig = inspect.signature(func)
            required = [
                p.name for p in sig.parameters.values()
                if p.default == inspect.Parameter.empty
            ]
            if required:
                parameters["required"] = required

        tool = Tool(
            name=name,
            func=func,
            description=description,
            parameters=parameters,
            write=write,
        )
        self._tools[name] = tool

    def call(self, name: str, **kwargs) -> Any:
        """Execute a tool by name."""
        if name not in self._tools:
            raise ValueError(f"Tool not found: {name}")
        return self._tools[name].func(**kwargs)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def is_write(self, name: str) -> bool:
        tool = self._tools.get(name)
        return tool.write if tool else False

    def schemas(self) -> list[dict]:
        """Return all tool schemas in OpenAI format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def write_tool_names(self) -> set[str]:
        return {name for name, t in self._tools.items() if t.write}

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def list(self) -> list[dict]:
        """Return all tools as list of dicts."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "write": t.write,
            }
            for t in self._tools.values()
        ]