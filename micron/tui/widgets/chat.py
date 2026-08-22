"""Chat log widget for micron TUI."""
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static


class ChatLog(VerticalScroll):
    """Scrollable chat history with Markdown assistant rendering."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_markdown: Markdown | None = None
        self._current_thinking: Static | None = None
        self._thinking_indicator: Static | None = None
        self._current_text: str = ""
        self._current_thinking_text: str = ""

    def add_user(self, text: str) -> None:
        self._reset_current()
        self.mount(Static(f"[b]You:[/b] {self._escape(text)}", classes="user-message"))
        self.scroll_end()

    def add_system(self, text: str) -> None:
        self._reset_current()
        self.mount(Static(self._escape(text), classes="system-message"))
        self.scroll_end()

    def add_thinking_indicator(self) -> None:
        self._reset_current()
        self._thinking_indicator = Static("⏳ Thinking...", classes="thinking-indicator")
        self.mount(self._thinking_indicator)
        self.scroll_end()

    def remove_thinking_indicator(self) -> None:
        if hasattr(self, "_thinking_indicator") and self._thinking_indicator is not None:
            self._thinking_indicator.remove()
            self._thinking_indicator = None

    def add_tool_result(self, name: str, summary: str) -> None:
        icon = "✓"
        esc = self._escape(summary) if summary else ""
        display = f"[dim]{icon} {name}:[/dim] {esc}" if summary else f"[dim]{icon} {name}[/dim]"
        self.mount(Static(display, classes="tool-result"))
        self.scroll_end()

    def start_assistant(self) -> None:
        self._reset_current()
        md = Markdown("", classes="assistant-message")
        self._current_markdown = md
        self._current_text = ""
        self.mount(md)
        self.scroll_end()

    def append_text(self, text: str) -> None:
        if self._current_markdown is None:
            self.start_assistant()
        self._current_text += text
        self._current_markdown.update(self._current_text)
        self.scroll_end()

    def start_thinking(self) -> None:
        if self._current_thinking is None:
            self._current_thinking = Static("🤔 Thinking...", classes="thinking-block")
            self.mount(self._current_thinking)
            self.scroll_end()

    def append_thinking(self, text: str) -> None:
        self.start_thinking()
        self._current_thinking_text += text
        self._current_thinking.update(self._current_thinking_text)
        self.scroll_end()

    def clear_log(self) -> None:
        self.remove_children()
        self._reset_current()

    def _reset_current(self) -> None:
        self.remove_thinking_indicator()
        self._current_markdown = None
        self._current_thinking = None
        self._current_text = ""
        self._current_thinking_text = ""

    @staticmethod
    def _escape(text: str) -> str:
        """Escape Rich markup so user text renders literally."""
        return text.replace("[", "[[")
