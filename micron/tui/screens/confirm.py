"""Confirmation screen for micron TUI."""
from typing import ClassVar

from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from micron.tui._markup import esc

_VERB = {
    "write_file": "write",
    "write_knowledge": "knowledge",
    "create_skill": "skill",
    "delete_file": "delete",
    "edit_file": "edit",
    "patch_file": "edit",
    "run_command": "run",
    "python_eval": "eval",
}


class ConfirmationScreen(Screen):
    """Compact modal confirmation dialog for pending write tools."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "decline", "Decline")]

    def __init__(self, pending_writes: list[dict], **kwargs):
        super().__init__(**kwargs)
        self.pending_writes = pending_writes

    def _summarize(self) -> str:
        n = len(self.pending_writes)
        noun = "operation" if n == 1 else "operations"
        parts = [f"[bold]{n} write {noun}[/bold]"]
        for w in self.pending_writes:
            name = w.get("tool_name", "?")
            args = w.get("args", {})
            verb = _VERB.get(name, name)
            detail = "?"
            if name == "write_file":
                detail = args.get("path", "?")
            elif name == "write_knowledge":
                detail = args.get("title", "?")
            elif name == "create_skill":
                detail = args.get("name", "?")
            elif name == "delete_file":
                detail = args.get("path", "?")
            elif name in ("edit_file", "patch_file"):
                detail = args.get("path", "?")
            elif name == "run_command":
                detail = args.get("cmd", "?")
            elif name == "python_eval":
                detail = ""
            safe_detail = esc(str(detail))
            parts.append(f"  [bold]{verb} {safe_detail}[/bold]" if detail else f"  [bold]{verb}[/bold]")
        return "\n".join(parts)

    def compose(self):
        with Vertical(id="confirm-dialog"):
            yield Static(self._summarize(), id="confirm-summary")
            with Horizontal(classes="confirm-buttons"):
                yield Button("No", id="confirm-no")
                yield Button("Yes", id="confirm-yes", variant="success")
                yield Button("Yes for Session", id="confirm-session", variant="success")

    def on_mount(self):
        self.query_one("#confirm-no", Button).focus()

    def _dismiss_with(self, confirmed: bool, remember: bool = False) -> None:
        self.dismiss({"confirm": confirmed, "remember": remember})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "confirm-yes":
            self._dismiss_with(True, False)
        elif bid == "confirm-session":
            self._dismiss_with(True, True)
        else:
            self._dismiss_with(False, False)

    def action_decline(self) -> None:
        self._dismiss_with(False, False)