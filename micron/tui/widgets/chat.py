"""Chat log widget for micron TUI."""
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static

from micron.tui._markup import esc


class ChatLog(VerticalScroll):
    """Scrollable chat history with Markdown assistant rendering."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_markdown: Markdown | None = None
        self._current_thinking: Static | None = None
        self._thinking_indicator: Static | None = None
        self._blink_timer = None
        self._blink_state = False
        self._current_text: str = ""
        self._current_thinking_text: str = ""

    def add_user(self, text: str) -> None:
        self._reset_current()
        self.mount(Static(f"▸ {esc(text)}", classes="user-message"))
        self.scroll_end()

    def add_system(self, text: str) -> None:
        self._reset_current()
        self.mount(Static(f"› {esc(text)}", classes="system-message"))
        self.scroll_end()

    def add_thinking_indicator(self) -> None:
        self._reset_current()
        self._thinking_indicator = Static("◉ thinking…", classes="thinking-indicator")
        self.mount(self._thinking_indicator)
        self._start_blink()
        self.scroll_end()

    def _start_blink(self) -> None:
        if self._blink_timer is not None:
            return
        self._blink_timer = self.set_interval(
            0.7, self._tick_blink, name="thinking-blink"
        )

    def _tick_blink(self) -> None:
        if self._thinking_indicator is None:
            self._stop_blink()
            return
        self._blink_state = not self._blink_state
        self._thinking_indicator.set_class(self._blink_state, "dimmed")

    def _stop_blink(self) -> None:
        if self._blink_timer is not None:
            self._blink_timer.stop()
            self._blink_timer = None

    def remove_thinking_indicator(self) -> None:
        self._stop_blink()
        if hasattr(self, "_thinking_indicator") and self._thinking_indicator is not None:
            self._thinking_indicator.remove()
            self._thinking_indicator = None

    def add_tool_result(self, name: str, summary: str) -> None:
        if summary:
            display = f"[#6b7280]✓[/] [bold]{esc(name)}[/bold] [#6b7280]{esc(summary)}[/#6b7280]"
        else:
            display = f"[#6b7280]✓[/] [bold]{esc(name)}[/bold]"
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
            self._current_thinking = Static("~ ", classes="thinking-block")
            self.mount(self._current_thinking)
            self.scroll_end()

    def append_thinking(self, text: str) -> None:
        self.start_thinking()
        self._current_thinking_text += text
        self._current_thinking.update(f"~ {esc(self._current_thinking_text)}")
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