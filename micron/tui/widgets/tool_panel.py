"""Tool panel widget for micron TUI."""
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from micron.tui._markup import esc


class ToolPanel(Vertical):
    """Displays running and completed tool calls as an activity stream."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls: list[dict] = []

    def compose(self):
        yield Static("Tool calls", id="tool-header")
        yield ListView(id="tool-list")

    def add_call(self, call_id: str, name: str, args: dict) -> None:
        if any(c["call_id"] == call_id for c in self.calls):
            return
        self.calls.append({
            "call_id": call_id,
            "name": name,
            "args": args,
            "status": "running",
            "summary": "",
            "result": None,
            "error": None,
        })
        self._refresh_list()

    def finish_call(self, call_id: str, summary: str = "", result=None, error: str = "") -> None:
        for call in self.calls:
            if call["call_id"] == call_id:
                call["summary"] = summary
                call["result"] = result
                call["error"] = error
                call["status"] = "error" if error else "done"
                break
        self._refresh_list()

    def clear_calls(self) -> None:
        self.calls.clear()
        self._refresh_list()

    def _refresh_list(self) -> None:
        lv = self.query_one("#tool-list", ListView)
        lv.clear()
        for call in self.calls:
            status = call["status"]
            if status == "running":
                icon = "◉"
                icon_color = "#f59e1b"
            elif status == "done":
                icon = "✓"
                icon_color = "#10b981"
            else:
                icon = "✗"
                icon_color = "#ef4444"

            summary = call["summary"] or ""
            if len(summary) > 60:
                summary = summary[:57] + "…"

            label = (
                f"[{icon_color}]{icon}[/{icon_color}] "
                f"[bold]{esc(call['name'])}[/bold]"
            )
            if summary:
                label += f" [dim]{esc(summary)}[/dim]"

            lv.append(ListItem(Static(label), name=call["call_id"]))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        call_id = event.item.name or ""
        for call in self.calls:
            if call["call_id"] == call_id:
                self.post_message(self.DetailRequested(call))
                break

    class DetailRequested(Message):
        """Posted when a tool row is selected for detail view."""

        def __init__(self, call: dict) -> None:
            super().__init__()
            self.call = call
