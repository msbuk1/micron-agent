"""Tool panel widget for micron TUI."""
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Static


class ToolPanel(Vertical):
    """Displays running and completed tool calls."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls: list[dict] = []

    def compose(self):
        yield Static("Tool calls", id="tool-header")
        yield DataTable(id="tool-table", show_cursor=True)

    def on_mount(self):
        table = self.query_one("#tool-table", DataTable)
        table.add_columns("Status", "Tool", "Summary")
        table.cursor_type = "row"
        table.zebra_stripes = True

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
        self._refresh_table()

    def finish_call(self, call_id: str, summary: str = "", result=None, error: str = "") -> None:
        for call in self.calls:
            if call["call_id"] == call_id:
                call["summary"] = summary
                call["result"] = result
                call["error"] = error
                call["status"] = "error" if error else "done"
                break
        self._refresh_table()

    def clear_calls(self) -> None:
        self.calls.clear()
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#tool-table", DataTable)
        table.clear()
        for call in self.calls:
            status = call["status"]
            icon = "⏳" if status == "running" else "✅" if status == "done" else "❌"
            summary = call["summary"]
            if len(summary) > 60:
                summary = summary[:57] + "..."
            table.add_row(icon, call["name"], summary, key=call["call_id"])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        call_id = event.row_key.value
        for call in self.calls:
            if call["call_id"] == call_id:
                self.post_message(self.DetailRequested(call))
                break

    class DetailRequested(Message):
        """Posted when a tool row is selected for detail view."""

        def __init__(self, call: dict) -> None:
            super().__init__()
            self.call = call
