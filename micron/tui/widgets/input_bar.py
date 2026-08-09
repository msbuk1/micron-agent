"""Input bar widget for micron TUI."""
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input


class InputBar(Horizontal):
    """Input area with send button and menu trigger."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pending = False

    def compose(self):
        yield Input(placeholder="Type a message or /command...", id="message-input")
        yield Button("Send", id="send-btn", variant="primary")
        yield Button("Menu", id="menu-btn")

    def on_mount(self):
        self.query_one("#message-input", Input).focus()

    def set_pending(self, pending: bool) -> None:
        """Disable/enable input while the agent is working."""
        self._pending = pending
        inp = self.query_one("#message-input", Input)
        send = self.query_one("#send-btn", Button)
        inp.disabled = pending
        send.disabled = pending
        if not pending:
            inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "message-input" and not self._pending:
            self.post_message(self.Submitted(event.value))
            event.input.value = ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            inp = self.query_one("#message-input", Input)
            if not self._pending:
                self.post_message(self.Submitted(inp.value))
                inp.value = ""
        elif event.button.id == "menu-btn":
            self.post_message(self.MenuRequested())

    class Submitted(Message):
        """Posted when the user submits a message."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class MenuRequested(Message):
        """Posted when the menu button is pressed."""
