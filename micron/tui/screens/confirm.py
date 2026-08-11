"""Confirmation screen for micron TUI."""
from typing import ClassVar

from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Static

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
        parts = [f"{n} write {noun}:"]
        for w in self.pending_writes:
            name = w.get("tool_name", "?")
            args = w.get("args", {})
            verb = _VERB.get(name, name)
            if name == "write_file":
                parts.append(f"  {verb} {args.get('path', '?')}")
            elif name == "write_knowledge":
                parts.append(f"  {verb} {args.get('title', '?')}")
            elif name == "create_skill":
                parts.append(f"  {verb} {args.get('name', '?')}")
            elif name == "delete_file":
                parts.append(f"  {verb} {args.get('path', '?')}")
            elif name in ("edit_file", "patch_file"):
                parts.append(f"  {verb} {args.get('path', '?')}")
            elif name == "run_command":
                parts.append(f"  {verb} {args.get('cmd', '?')}")
            elif name == "python_eval":
                parts.append(f"  {verb}")
            else:
                parts.append(f"  {verb}")
        return "\n".join(parts)

    def compose(self):
        with Vertical(id="confirm-dialog"):
            yield Static(self._summarize(), id="confirm-summary")
            yield Checkbox("Remember for this session", id="confirm-remember")
            with Horizontal(classes="confirm-buttons"):
                yield Button("No", id="confirm-no", variant="error")
                yield Button("Yes", id="confirm-yes", variant="success")

    def on_mount(self):
        self.query_one("#confirm-no", Button).focus()

    def _dismiss_with(self, confirmed: bool) -> None:
        remember = self.query_one("#confirm-remember", Checkbox).value
        self.dismiss({"confirm": confirmed, "remember": remember})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._dismiss_with(event.button.id == "confirm-yes")

    def action_decline(self) -> None:
        self._dismiss_with(False)
