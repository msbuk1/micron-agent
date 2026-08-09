"""Plugin system — drop-in tools defined in ``context/plugins/``.

Plugins share the same ``@tool`` decorator as built-ins (the single source
of truth lives in ``micron/tools/decorator.py``). A plugin is just a tool
that lives in ``context/plugins/`` and is discovered by scanning that
directory at agent startup.

Usage:
    from micron.tools.decorator import tool

    @tool(name="hello", description="Say hello")
    def hello(name: str = "world") -> str:
        return f"Hello, {name}!"
"""
from micron.tools.decorator import (
    ToolDescriptor,
    _registry,
    clear,
    tool,
)

__all__ = ["tool", "ToolDescriptor", "_registry", "clear"]
