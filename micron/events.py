"""Common event handling for agent generators.

Both CLI and server consume the same agent event stream but handle different
subsets. This module provides a single routing function so event types and
accumulation logic live in one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generator


class EventType:
    """Canonical event type names — single source of truth."""
    TEXT = "text"
    THINKING = "thinking"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    ERROR = "error"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DONE = "done"


@dataclass
class EventResult:
    """Accumulated state after processing a generator."""
    text: str = ""
    pending_writes: list[dict] | None = None


def process_events(
    generator: Generator[dict, None, None],
    *,
    on_text: Callable[[str], None] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    on_tool_start: Callable[[str, str], None] | None = None,
    on_tool_result: Callable[[str, str], None] | None = None,
    on_tool_error: Callable[[str, str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_confirmation_required: Callable[[list[dict]], None] | None = None,
    on_done: Callable[[], None] | None = None,
) -> EventResult:
    """Route agent events to callbacks.

    Walks the generator, dispatches each chunk to the matching callback,
    accumulates text, and tracks pending writes.

    Args:
        generator: Agent.run() generator yielding event dicts.
        on_text: Called with each text chunk content.
        on_thinking: Called with reasoning/thinking content.
        on_tool_start: Called with (tool_name, call_id).
        on_tool_result: Called with (tool_name, summary).
        on_tool_error: Called with (tool_name, error_message).
        on_error: Called with error message string.
        on_confirmation_required: Called with pending_writes list.
        on_done: Called when the generator ends.

    Returns:
        EventResult with accumulated text and pending writes.
    """
    result = EventResult()

    for chunk in generator:
        event_type = chunk.get("type")

        if event_type == EventType.TEXT:
            result.text += chunk["content"]
            if on_text:
                on_text(chunk["content"])

        elif event_type == EventType.THINKING:
            if on_thinking:
                on_thinking(chunk["content"])

        elif event_type == EventType.TOOL_START:
            if on_tool_start:
                on_tool_start(chunk["name"], chunk["call_id"])

        elif event_type == EventType.TOOL_RESULT:
            if on_tool_result:
                on_tool_result(chunk["name"], chunk.get("summary", ""))

        elif event_type == EventType.TOOL_ERROR:
            if on_tool_error:
                on_tool_error(chunk["name"], chunk.get("error", ""))

        elif event_type == EventType.ERROR:
            if on_error:
                on_error(chunk.get("message", ""))

        elif event_type == EventType.CONFIRMATION_REQUIRED:
            result.pending_writes = chunk.get("pending_writes", [])
            if on_confirmation_required:
                on_confirmation_required(result.pending_writes)

        elif event_type == EventType.DONE:
            if on_done:
                on_done()
            break

    return result
