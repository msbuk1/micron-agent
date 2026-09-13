"""Turn/Step lifecycle — inbox, hooks, and event helpers.

A **turn** is zero or more **steps**; a step is one model request plus the
tools it calls. Input reaches the driver through one :class:`Inbox`:

- ``submit(message)`` (what ``MicronAgent.run`` does) wakes the driver
  immediately and opens a turn.
- ``inject(text)`` (what ``MicronAgent.inject`` does) queues context that
  waits until the next admitted request — never mid-stream.

Two interception hooks live on :class:`TurnHooks`:

- ``pre_step(message)`` — may rewrite the claimed input (return the new
  string) or reject it (return ``None`` or ``""``). A rejected/empty first
  claim closes the turn with no step.
- ``should_stop()`` — checked before each step; returning ``True`` ends
  the turn early.

Both default to pass-through. Subclass or assign ``agent.hooks`` to
intercept; no loop changes required.
"""
from __future__ import annotations

import itertools


class TurnHooks:
    """Pass-through lifecycle hooks — override to intercept."""

    def pre_step(self, message: str) -> str | None:
        """Rewrite or reject claimed input before the first step.

        Return the (possibly rewritten) message, or ``None``/``""`` to
        reject — a rejected claim closes the turn with no step.
        """
        return message

    def should_stop(self) -> bool:
        """Return True to end the turn before the next step."""
        return False


class Inbox:
    """One inbox for driver input: wake messages + injected context."""

    def __init__(self):
        self._injected: list[str] = []

    def inject(self, text: str) -> None:
        """Queue context. Lands in the next admitted request, never mid-stream."""
        self._injected.append(text)

    def drain(self) -> list[str]:
        """Return and clear queued injected context."""
        out, self._injected = self._injected, []
        return out

    def __len__(self) -> int:
        return len(self._injected)


_turn_ids = itertools.count(1)


def new_turn_id() -> str:
    return f"turn_{next(_turn_ids)}"
