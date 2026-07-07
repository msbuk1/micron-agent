"""Plugin system — @tool decorator for defining tools as Python functions.

Usage:
    from micron.plugins import tool

    @tool(name="hello", description="Say hello")
    def hello(name: str = "world") -> str:
        return f"Hello, {name}!"
"""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolDescriptor:
    """Describes a plugin tool function."""

    name: str
    description: str
    func: Callable
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    write: bool = False


# Global registry — populated by @tool decorator on import
_registry: list[ToolDescriptor] = []


def tool(*, name: str, description: str, write: bool = False):
    """Decorator that registers a function as a plugin tool.

    Args:
        name: Tool name (used by the LLM to call it).
        description: Description shown in the system prompt.
        write: If True, tool requires user confirmation before execution.
    """
    def decorator(func: Callable) -> Callable:
        td = ToolDescriptor(
            name=name,
            description=description,
            func=func,
            parameters=_infer_parameters(func),
            write=write,
        )
        _registry.append(td)
        return func
    return decorator


def _infer_parameters(func: Callable) -> dict:
    """Infer an OpenAI-compatible parameter schema from a function's signature."""
    import inspect

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
    """Clear the plugin registry (for testing)."""
    _registry.clear()
