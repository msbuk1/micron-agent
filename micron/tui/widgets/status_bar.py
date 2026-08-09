"""Status bar widget for micron TUI."""
from textual.widgets import Static


class StatusBar(Static):
    """Footer showing session, model, and resource counts."""

    def update_status(
        self,
        session_id: str = "",
        provider: str = "",
        model: str = "",
        memory_count: int = 0,
        knowledge_count: int = 0,
        skill_count: int = 0,
        status: str = "",
    ) -> None:
        parts = [f"session={session_id[:8]}" if session_id else "session=-"]
        if provider:
            parts.append(f"provider={provider}")
        if model:
            parts.append(f"model={model}")
        parts.extend([
            f"mems={memory_count}",
            f"kb={knowledge_count}",
            f"skills={skill_count}",
        ])
        if status:
            parts.append(f"[{status}]")
        self.update("  ".join(parts))
