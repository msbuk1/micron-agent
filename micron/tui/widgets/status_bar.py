"""Status bar widget for micron TUI."""
from textual.containers import Horizontal
from textual.widgets import Static

from micron.tui._markup import esc


class StatusBar(Horizontal):
    """Footer showing session, model, and resource counts as a readout."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._blink_timer = None
        self._blink_state = False

    def compose(self):
        yield Static("", id="status-left")
        yield Static("", id="status-right")

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
        left = self.query_one("#status-left", Static)
        right = self.query_one("#status-right", Static)

        beacon = self._beacon(status)
        sid = esc(session_id[:8]) if session_id else "-"
        session = f"[dim]session[/dim] {sid}"
        prov = f"[dim]{esc(provider)}[/dim]" if provider else ""
        mod = f"[bold]{esc(model)}[/bold]" if model else ""
        model_part = f"{prov}/{mod}" if provider and model else (prov or mod)

        active = self._is_active(status)
        if active:
            self._start_blink(left)
        else:
            self._stop_blink(left)
        left.update(f"{beacon} {session}  {model_part}")

        counts = f"mems={memory_count}  kb={knowledge_count}  skills={skill_count}"
        status_text = self._status_text(status)
        right.update(f"[dim]{counts}[/dim]  {status_text}")

    def _start_blink(self, widget: Static) -> None:
        if self._blink_timer is not None:
            return
        self._blink_state = False
        widget.set_class(False, "beacon-dimmed")
        self._blink_timer = self.set_interval(
            0.7, lambda: self._tick_blink(widget), name="beacon-blink"
        )

    def _tick_blink(self, widget: Static) -> None:
        self._blink_state = not self._blink_state
        widget.set_class(self._blink_state, "beacon-dimmed")

    def _stop_blink(self, widget: Static) -> None:
        if self._blink_timer is not None:
            self._blink_timer.stop()
            self._blink_timer = None
        widget.set_class(False, "beacon-dimmed")

    @staticmethod
    def _beacon(status: str) -> str:
        if status in ("thinking", "tool:", "confirming writes") or status.startswith("tool:"):
            return "[#f59e1b bold]◉[/#f59e1b bold]"
        if status == "ready":
            return "[#10b981]◉[/#10b981]"
        if status == "error":
            return "[#ef4444]◉[/#ef4444]"
        return "[#6b7280]◎[/#6b7280]"

    @staticmethod
    def _is_active(status: str) -> bool:
        return (
            status in ("thinking", "confirming writes")
            or status.startswith("tool:")
        )

    @staticmethod
    def _status_text(status: str) -> str:
        if not status:
            return ""
        safe = esc(status)
        if status == "ready":
            return f"[#10b981]{safe}[/#10b981]"
        if status == "error":
            return f"[#ef4444 bold]{safe}[/#ef4444 bold]"
        if status in ("thinking", "confirming writes") or status.startswith("tool:"):
            return f"[#f59e1b bold]{safe}[/#f59e1b bold]"
        return f"[#6b7280]{safe}[/#6b7280]"