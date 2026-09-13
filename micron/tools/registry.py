"""Tool registry — manages tool registration and execution."""
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from micron.error_format import format_error
from micron.tools.pipeline import (
    ListenerRegistry,
    ToolInvocation,
    ToolListener,
    ToolScopeListener,
)


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
        self._listeners = ListenerRegistry()

    def add_listener(self, listener: ToolListener) -> None:
        """Add a waterfall listener (see micron.tools.pipeline)."""
        self._listeners.add(listener)

    @property
    def listeners(self) -> ListenerRegistry:
        return self._listeners

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

    def call(self, name: str, *, _emit: Callable[[dict], None] | None = None,
             _call_id: str = "", **kwargs) -> Any:
        """Execute a tool through the waterfall pipeline.

        Emits pipeline events via ``_emit`` (when given):
        ``tool_pre`` before pre-execute, ``tool_post`` after post-execute,
        and ``tool_error`` when a pre-execute listener short-circuits.

        A ``timeout`` kwarg is popped and enforced as an outer cap on the
        tool execution; it never leaks into tool signatures.
        """
        timeout = kwargs.pop("timeout", None)
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Tool not found: {name}")
        return self._run_pipeline(tool, _emit=_emit, _call_id=_call_id,
                                  _timeout=timeout, **kwargs)

    def _run_pipeline(self, tool: Tool, *, _emit: Callable[[dict], None] | None,
                      _call_id: str, _timeout: float | None = None, **kwargs) -> Any:
        """Run one resolved tool through the listener chain.

        Split from :meth:`call` so scoped views can route out-of-scope
        (but parent-known) calls through the same pipeline — the scope
        listener owns the denial (ADR 0008), not an if-check here.
        """
        name = tool.name
        emit = _emit or (lambda ev: None)
        invocation = ToolInvocation(name=name, args=dict(kwargs), call_id=_call_id)

        emit({"type": "tool_pre", "name": name, "call_id": _call_id, "args": invocation.args})

        executed = False

        def execute() -> Any:
            nonlocal executed
            executed = True
            # Execute with invocation.args (pre-execute listeners may
            # rewrite them — e.g. SandboxListener argv-wrapping).
            return self._execute_with_timeout(tool, invocation.args, _timeout)

        result = self._listeners.run_pre(invocation, execute)

        if not executed:
            # Short-circuit: denial/approval — no tool ran. Render as
            # tool_error via ErrorFormat (single error-copy seam).
            msg = format_error(str(result), tool=name).removeprefix("Error: ").lstrip()
            emit({"type": "tool_error", "name": name, "call_id": _call_id, "error": msg})
            return result

        result = self._listeners.run_post(invocation, result)
        emit({"type": "tool_post", "name": name, "call_id": _call_id, "result": result})
        return result

    @staticmethod
    def _execute_with_timeout(tool: Tool, args: dict, timeout: float | None) -> Any:
        """Run the tool function, enforcing ``timeout`` as an outer cap."""
        if timeout is None:
            return tool.func(**args)
        import concurrent.futures

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(tool.func, **args)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(
                    f"Tool '{tool.name}' timed out after {timeout}s"
                ) from None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

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


class ScopedToolRegistry(ToolRegistry):
    """Isolated view over a parent ToolRegistry (issue #18).

    One session/agent can run with a different capability set than the
    global registry (plan mode, a reduced subagent toolset) while the
    parent keeps the full set. The view shares the parent's ``Tool``
    objects — one definition, many scopes — and enforces the boundary in
    the waterfall pipeline via ``ToolScopeListener`` (ADR 0008), so
    out-of-scope calls are denied at pre-execute even if the model
    hallucinates them. Prompt assembly and ``stream_chat(tools=...)``
    only ever see in-scope schemas because they read from this view.

    The view is a snapshot of the parent at construction; listeners present
    on the parent at that moment are inherited (scope listener outermost)
    so policy listeners like ``CommandPolicyListener`` still apply inside
    the scope.
    """

    def __init__(self, parent: ToolRegistry, tools: Iterable[str]):
        super().__init__()
        self._parent = parent
        requested = list(tools)
        known = {t.name for t in parent.all()}
        unknown = sorted(set(requested) - known)
        if unknown:
            raise ValueError(
                f"Unknown tool(s) in scope: {unknown}. "
                f"Parent registry has: {sorted(known)}"
            )
        for name in requested:
            self._tools[name] = parent.get(name)
        # Scope boundary first (outermost — sees every call before any
        # policy listener), then the parent's inherited listeners.
        self.add_listener(ToolScopeListener(set(requested)))
        for listener in parent.listeners.all():
            self.add_listener(listener)

    def register(
        self,
        name: str,
        func: Callable,
        description: str,
        parameters: dict,
        write: bool = False,
    ):
        """Register a tool — scope is a capability boundary, so only
        in-scope names may be (re-)registered, and the write goes to the
        parent registry to keep the two views in sync."""
        if name not in self._tools:
            raise ValueError(
                f"Cannot register '{name}' outside this registry's scope "
                f"({sorted(self._tools)}). Register it on the parent registry."
            )
        self._parent.register(name, func, description, parameters, write)
        self._tools[name] = self._parent.get(name)

    def call(self, name: str, *, _emit: Callable[[dict], None] | None = None,
             _call_id: str = "", **kwargs) -> Any:
        """Execute a tool through this view's waterfall pipeline.

        Out-of-scope names resolve against the parent and still flow
        through the pipeline, where ``ToolScopeListener`` (outermost)
        denies them — enforcement lives in the pipeline, not in an
        if-check at the call site. Names unknown to both registries raise
        ``ValueError`` as usual.
        """
        tool = self._tools.get(name) or self._parent.get(name)
        if tool is None:
            raise ValueError(f"Tool not found: {name}")
        timeout = kwargs.pop("timeout", None)
        return self._run_pipeline(tool, _emit=_emit, _call_id=_call_id,
                                  _timeout=timeout, **kwargs)