"""Help screen for micron TUI."""
from typing import ClassVar

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Markdown

HELP_TEXT = """
# micron shortcuts

**Keyboard**

- `Ctrl+Q` — Quit
- `Ctrl+L` — Clear chat history
- `Ctrl+K` — Focus input
- `Ctrl+B` — Toggle sidebar
- `Ctrl+/` — Show this help
- `Enter` — Send message
- `Shift+Enter` — Insert newline (multiline)
- `Up` / `Down` — Recall input history (prefix-filtered)
- `Ctrl+R` — Search history (reverse-i-search)
- `Tab` — Autocomplete slash command

**Slash commands**

- `/help` — Show this help
- `/exit` or `/quit` — Exit micron
- `/clear` — Clear conversation history
- `/mem` — Refresh memory list
- `/memory delete <id>` — Delete a single memory by id
- `/memory list` — List recent memories
- `/tools` — Show available tools
- `/providers` — List configured providers
- `/model` — Open model picker / switch provider+model (alias: `/models`)
- `/unload` — Unload model from RAM
- `/reload` — Reload skills from disk
- `/sessions` — List recent sessions (shows IDs for `/resume`)
- `/resume ID` — Resume a previous session (IDs from `/sessions` or click Sessions tab)
- `/last` — Show last assistant response
- `/trash` — List recoverable files
- `/restore F` — Restore a file from trash
- `/purge` — Empty trash permanently
- `/undo F` — Restore file from .bak backup
- `/tree` — Show directory tree
- `/skill NAME` — Load a procedure skill
- `/skills` — List procedure skills
"""


class HelpScreen(Screen):
    """Modal help screen."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "dismiss", "Close")]

    def compose(self):
        with Vertical(id="help-dialog"):
            yield Markdown(HELP_TEXT)
            yield Button("Close", id="help-close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self.dismiss()
