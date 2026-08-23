"""History search screen for micron TUI (Ctrl+R)."""
from typing import ClassVar

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, ListItem, ListView, Static

from micron.tui._markup import esc


class HistorySearchScreen(Screen):
    """Reverse-i-search overlay: type to filter, Enter to select."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "dismiss", "Close"),
        ("ctrl+r", "dismiss", "Close"),
    ]

    def __init__(self, history: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        # most recent last → show most recent first in list
        self._all = list(reversed(history))

    def compose(self):
        with Vertical(id="history-dialog"):
            yield Static("History search (type to filter, Enter to select):", id="history-title")
            yield Input(placeholder="Search history...", id="history-input")
            yield ListView(id="history-list")

    def on_mount(self) -> None:
        lv = self.query_one("#history-list", ListView)
        self._refresh("")
        self.query_one("#history-input", Input).focus()
        lv.index = 0

    def _refresh(self, query: str) -> None:
        lv = self.query_one("#history-list", ListView)
        lv.clear()
        q = query.lower()
        shown = 0
        for h in self._all:
            if q and q not in h.lower():
                continue
            lv.append(ListItem(Static(esc(h))))
            shown += 1
            if shown >= 50:
                break
        if shown == 0:
            lv.append(ListItem(Static("[dim italic]no matches[/dim italic]")))

    def on_input_changed(self, event: Input.Changed) -> None:
        if getattr(event.input, "id", None) != "history-input":
            return
        self._refresh(event.value or "")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if getattr(event.input, "id", None) != "history-input":
            return
        # Enter in the search box selects the top hit
        lv = self.query_one("#history-list", ListView)
        idx = getattr(lv, "index", 0) or 0
        self._select(idx)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._select(event.list_view.index or 0)

    def _select(self, idx: int) -> None:
        lv = self.query_one("#history-list", ListView)
        query = self.query_one("#history-input", Input).value or ""
        q = query.lower()
        filtered = [h for h in self._all if not q or q.lower() in h.lower()]
        if 0 <= idx < len(filtered):
            self.dismiss(filtered[idx])
        else:
            self.dismiss(None)