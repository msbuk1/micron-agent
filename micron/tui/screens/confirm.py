"""Confirmation screen for micron TUI."""
from typing import ClassVar

from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static


class ConfirmationScreen(Screen):
    """Modal confirmation dialog for pending write tools."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "decline", "Decline")]

    def __init__(self, pending_writes: list[dict], **kwargs):
        super().__init__(**kwargs)
        self.pending_writes = pending_writes

    def compose(self):
        lines = ["The agent wants to perform the following write operations:", ""]
        for w in self.pending_writes:
            name = w.get("tool_name", "?")
            args = w.get("args", {})
            if name == "write_file":
                lines.append(f"  • Write file: {args.get('path', '?')}")
            elif name == "write_knowledge":
                lines.append(f"  • Write knowledge: {args.get('title', '?')}")
            elif name == "create_skill":
                lines.append(f"  • Create skill: {args.get('name', '?')}")
            elif name == "delete_file":
                lines.append(f"  • Delete file: {args.get('path', '?')}")
            elif name == "edit_file":
                lines.append(f"  • Edit file: {args.get('path', '?')}")
            elif name == "patch_file":
                lines.append(f"  • Patch file: {args.get('path', '?')}")
            elif name == "run_command":
                lines.append(f"  • Run command: {args.get('command', '?')}")
            elif name == "python_eval":
                lines.append("  • Execute Python code")
            else:
                lines.append(f"  • {name}({args})")
        lines.extend(["", "Proceed?"])

        with Vertical(id="confirm-dialog"):
            yield Static("\n".join(lines))
            with Horizontal():
                yield Button("No", id="confirm-no", variant="error")
                yield Button("Yes", id="confirm-yes", variant="success")

    def on_mount(self):
        self.query_one("#confirm-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_decline(self) -> None:
        self.dismiss(False)
