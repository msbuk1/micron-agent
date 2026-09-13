"""Waterfall tool pipeline — pre/post-execute interception with next() delegation.

Every ``ToolRegistry.call`` flows through a listener chain::

    pre-execute -> execute -> post-execute

Listeners observe or own a call:

- **Observe / annotate** — call ``next()`` (``next(result)`` in post-execute)
  to delegate to the rest of the chain (and eventually the tool). Whatever
  ``next()`` returns flows back through the listener, which may annotate it.
- **Short-circuit** — return *without* calling ``next()``. In pre-execute
  this denies the call: the tool never runs and the returned value is
  rendered as a ``tool_error`` via ``ErrorFormat``. In post-execute it
  replaces the result.

The first listener added is the outermost (sees the call first).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolInvocation:
    """Everything a listener needs to know about one tool call."""

    name: str
    args: dict
    call_id: str = ""
    metadata: dict = field(default_factory=dict)


class ToolListener:
    """Base listener — delegates by default.

    Subclasses override ``pre_execute`` / ``post_execute``. Calling
    ``next()`` delegates; returning without calling it short-circuits.
    """

    def pre_execute(self, invocation: ToolInvocation, next: Callable[[], Any]) -> Any:
        return next()

    def post_execute(
        self, invocation: ToolInvocation, result: Any, next: Callable[[Any], Any]
    ) -> Any:
        return next(result)


class ListenerRegistry:
    """Ordered listener chain with waterfall ``next()`` semantics."""

    def __init__(self):
        self._listeners: list[ToolListener] = []

    def add(self, listener: ToolListener) -> None:
        """Append a listener. Earlier additions sit outermost in the chain."""
        self._listeners.append(listener)

    def all(self) -> list[ToolListener]:
        return list(self._listeners)

    def __len__(self) -> int:
        return len(self._listeners)

    def run_pre(self, invocation: ToolInvocation, execute: Callable[[], Any]) -> Any:
        """Run the pre-execute chain; ``execute`` sits at the innermost slot."""
        chain = execute
        for listener in reversed(self._listeners):
            chain = self._wrap_pre(listener, invocation, chain)
        return chain()

    def run_post(self, invocation: ToolInvocation, result: Any) -> Any:
        """Run the post-execute chain over ``result``."""
        chain: Callable[[Any], Any] = lambda r: r
        for listener in reversed(self._listeners):
            chain = self._wrap_post(listener, invocation, chain)
        return chain(result)

    @staticmethod
    def _wrap_pre(
        listener: ToolListener, invocation: ToolInvocation, nxt: Callable[[], Any]
    ) -> Callable[[], Any]:
        def call():
            return listener.pre_execute(invocation, nxt)

        return call

    @staticmethod
    def _wrap_post(
        listener: ToolListener,
        invocation: ToolInvocation,
        nxt: Callable[[Any], Any],
    ) -> Callable[[Any], Any]:
        def call(result: Any):
            return listener.post_execute(invocation, result, nxt)

        return call


class CommandPolicyListener(ToolListener):
    """Pre-execute listener routing ``run_command`` through ``CommandPolicy``.

    Single implementation of the blocklist denial path: a ``Deny`` decision
    short-circuits (returns the reason without calling ``next()``), so the
    tool never executes and the registry renders it as a ``tool_error``.
    """

    def pre_execute(self, invocation: ToolInvocation, next: Callable[[], Any]) -> Any:
        if invocation.name != "run_command":
            return next()
        from micron.tools.command_policy import Deny, evaluate_command

        decision = evaluate_command(invocation.args.get("cmd", ""))
        if isinstance(decision, Deny):
            return decision.reason
        return next()
