"""Shared tool-definition decorator for micron.

Single source of truth for how a tool is declared, regardless of whether it
is a built-in (in ``micron/tools/builtin.py``) or a user plugin (in
``context/plugins/``). Derives an OpenAI-compatible JSON schema from the
function signature and merges in optional per-parameter descriptions.

Usage::

    from micron.tools.decorator import tool

    @tool(
        name="web_search",
        description="Search the web for current information",
        query="Search query - use keywords, not a question",
        max_results="Number of results to return (default 5)",
    )
    def web_search(query: str, max_results: int = 5) -> list[dict]:
        ...
"""
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolDescriptor:
    """Describes a tool function."""

    name: str
    description: str
    func: Callable
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    write: bool = False


# Global registry — populated by @tool decorator on import
_registry: list[ToolDescriptor] = []


def tool(*, name: str, description: str, write: bool = False, **param_descs):
    """Register a function as a tool.

    Auto-derives the JSON parameter schema from the function signature.
    ``param_descs`` maps parameter name -> human-readable description, which
    is merged into the schema's ``properties[<name>]["description"]``.

    Args:
        name: Tool name (used by the LLM to call it).
        description: Description shown in the system prompt.
        write: If True, tool requires user confirmation before execution.
        **param_descs: Optional per-parameter descriptions.

    The decorator returns the original callable unchanged (no wrapping).
    """
    def decorator(func: Callable) -> Callable:
        schema = _infer_parameters(func)
        props = schema["properties"]
        for pname, desc in param_descs.items():
            if pname in props:
                props[pname]["description"] = desc
        td = ToolDescriptor(
            name=name,
            description=description,
            func=func,
            parameters=schema,
            write=write,
        )
        _registry.append(td)
        return func
    return decorator


def _infer_parameters(func: Callable) -> dict:
    """Infer an OpenAI-compatible parameter schema from a function's signature."""
    sig = inspect.signature(func)
    properties = {}
    required = []

    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue

        # Determine JSON type from annotation
        anno = param.annotation if param.annotation is not inspect.Parameter.empty else str
        if anno in (int, float):
            json_type = "number" if anno is float else "integer"
        elif anno is bool:
            json_type = "boolean"
        elif anno is list:
            json_type = "array"
        elif anno is dict:
            json_type = "object"
        else:
            json_type = "string"

        properties[pname] = {"type": json_type}

        if param.default is inspect.Parameter.empty:
            required.append(pname)

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def clear():
    """Clear the shared registry (for testing)."""
    _registry.clear()
