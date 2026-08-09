"""Agent worker for micron TUI.

Runs the synchronous agent generator in a Textual worker thread and posts
events back to the app via thread-safe messages.
"""
import asyncio

from textual.message import Message


class AgentEvent(Message):
    """A single event chunk from the agent generator."""

    def __init__(self, event: dict) -> None:
        super().__init__()
        self.event = event


class AgentDone(Message):
    """Posted when an agent run completes."""

    def __init__(self, text: str = "", pending_writes: list[dict] | None = None) -> None:
        super().__init__()
        self.text = text
        self.pending_writes = pending_writes


class AgentError(Message):
    """Posted when an agent run raises an unexpected exception."""

    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


def _iterate_agent(
    app,
    agent,
    query: str,
    *,
    history: list[dict] | None = None,
    confirm: bool = False,
    pending_tool_calls=None,
):
    """Shared iterator used by both sync and async worker variants."""
    try:
        generator = agent.run(
            query,
            history=history,
            stream=True,
            confirm=confirm,
            pending_tool_calls=pending_tool_calls,
        )
        for chunk in generator:
            app.post_message(AgentEvent(chunk))
    except Exception as exc:  # noqa: BLE001 - worker errors bubble via message
        app.post_message(AgentError(str(exc)))
    else:
        app.post_message(AgentDone())


def run_agent(
    app,
    agent,
    query: str,
    *,
    history: list[dict] | None = None,
    confirm: bool = False,
    pending_tool_calls=None,
) -> None:
    """Synchronous function intended to run inside a threaded Textual worker."""
    _iterate_agent(app, agent, query, history=history, confirm=confirm, pending_tool_calls=pending_tool_calls)


async def run_agent_async(
    app,
    agent,
    query: str,
    *,
    history: list[dict] | None = None,
    confirm: bool = False,
    pending_tool_calls=None,
) -> None:
    """Asynchronous function intended to run inside a non-threaded Textual worker."""
    # Use asyncio.sleep(0) to yield control back to the event loop between chunks.
    try:
        generator = agent.run(
            query,
            history=history,
            stream=True,
            confirm=confirm,
            pending_tool_calls=pending_tool_calls,
        )
        for chunk in generator:
            app.post_message(AgentEvent(chunk))
            await asyncio.sleep(0)
    except Exception as exc:  # noqa: BLE001 - worker errors bubble via message
        app.post_message(AgentError(str(exc)))
    else:
        app.post_message(AgentDone())
