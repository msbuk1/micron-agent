"""Main Textual app for micron TUI."""
from __future__ import annotations

import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Label, LoadingIndicator, Markdown, Static

from micron.agent import ToolCall
from micron.events import EventType
from micron.tui.commands import CommandDispatcher
from micron.tui.screens.confirm import ConfirmationScreen
from micron.tui.screens.help import HelpScreen
from micron.tui.screens.history import HistorySearchScreen
from micron.tui.screens.models import ModelPickerScreen
from micron.tui.widgets.chat import ChatLog
from micron.tui.widgets.input_bar import InputBar
from micron.tui.widgets.sidebar import Sidebar
from micron.tui.widgets.status_bar import StatusBar
from micron.tui.widgets.tool_panel import ToolPanel
from micron.tui.worker import AgentDone, AgentError, AgentEvent, run_agent, run_agent_async


class MicronTUI(App):
    """Full-screen terminal interface for micron."""

    CSS_PATH = "app.tcss"

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+l", "clear_history", "Clear"),
        ("ctrl+k", "focus_input", "Input"),
        ("ctrl+b", "toggle_sidebar", "Sidebar"),
        ("ctrl+slash", "show_help", "Help"),
        ("ctrl+r", "history_search", "History"),
        ("escape", "cancel_agent", "Cancel"),
    ]

    conversation_history: reactive[list[dict]] = reactive(list)
    active_skill = reactive(None)

    def __init__(
        self,
        agent_factory: Callable[[], tuple],
        *,
        title: str = "micron",
        thread_workers: bool = True,
        config: Any = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.title = title
        self._thread_workers = thread_workers
        self._agent_factory = agent_factory
        self._agent = None
        self._session_logger = None
        self._session_id = ""
        self._pending_writes: list[dict] | None = None
        self._current_query: str = ""
        self._current_user_text: str = ""
        self._current_history: list[dict] | None = None
        self._current_assistant_text: str = ""
        self._commands: CommandDispatcher | None = None
        self._config = config
        # Session-level override set when the user checks "Remember for this session".
        # One of None (no override), "allow", "deny".
        self._session_confirm_writes: str | None = None
        # Input history for Up/Down recall (like shell)
        self._input_history: list[str] = []
        self._history_index: int = -1
        self._history_draft: str = ""
        self._history_filtered: list[str] | None = None
        # Active Textual Worker for the running agent (for Esc/Stop)
        self._agent_worker = None
        self._agent_worker_name: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            with Horizontal(id="top"):
                with Vertical(id="chat-container"):
                    yield ChatLog(id="chat-log")
                yield Sidebar(id="sidebar")
            yield ToolPanel(id="tool-panel")
            yield InputBar(id="input-bar")
            yield Static("", id="suggest-bar", classes="hidden")
            yield StatusBar(id="status-bar")
        with Vertical(id="loading-overlay"), Vertical(id="loading-dialog"):
            yield Label("Loading micron...")
            yield LoadingIndicator(id="loading-spinner")

    def on_mount(self) -> None:
        self.run_worker(self._init_agent, thread=self._thread_workers, name="init_agent")

    async def _init_agent(self) -> None:
        self._agent, self._session_logger, self._session_id = self._agent_factory()
        self._commands = CommandDispatcher(self, self._agent, self._session_logger, {})
        if self._thread_id == threading.get_ident():
            self._on_agent_ready()
        else:
            self.call_from_thread(self._on_agent_ready)

    def _history_path(self) -> Path | None:
        try:
            if self._agent is not None and hasattr(self._agent, "context_dir"):
                return Path(self._agent.context_dir) / "input_history.jsonl"
            if self._config is not None:
                ctx = self._config.get("context_dir", "context")
                if ctx:
                    return Path(ctx) / "input_history.jsonl"
        except Exception:
            pass
        return None

    def _load_history(self) -> None:
        path = self._history_path()
        if path is None or not path.exists():
            return
        try:
            import json

            loaded: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    t = obj.get("t") if isinstance(obj, dict) else str(obj)
                except Exception:
                    t = line
                if t:
                    loaded.append(t)
            # keep last 500, dedupe consecutive already handled on append
            self._input_history = loaded[-500:]
            self._history_index = -1
        except Exception as exc:  # noqa: BLE001
            self.log(f"load history failed: {exc}")

    def _append_history(self, text: str) -> None:
        path = self._history_path()
        if path is None:
            return
        try:
            import json

            path.parent.mkdir(parents=True, exist_ok=True)
            # append
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": text}, ensure_ascii=False) + "\n")
            # enforce 500 limit by trimming oldest if needed
            if len(self._input_history) > 500:
                # rewrite trimmed
                trimmed = self._input_history[-500:]
                self._input_history = trimmed
                with path.open("w", encoding="utf-8") as f:
                    for t in trimmed:
                        f.write(json.dumps({"t": t}, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            self.log(f"append history failed: {exc}")

    def _on_agent_ready(self) -> None:
        loading = self.query_one("#loading-overlay", Vertical)
        loading.display = False
        self._load_history()
        self._refresh_sidebar()
        self._update_status("ready")
        self.query_one("#message-input").focus()

    def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        text = event.text.strip()
        # hide suggestions on submit
        try:
            self.query_one("#suggest-bar", Static).add_class("hidden")
        except Exception:
            pass
        if not text:
            return
        # record in input history (Up/Down recall)
        if not self._input_history or self._input_history[-1] != text:
            self._input_history.append(text)
            self._append_history(text)
        self._history_index = -1
        self._history_draft = ""
        self._history_filtered = None
        if text.startswith("/"):
            self._handle_command(text)
            return
        self._run_user_message(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        if getattr(event.input, "id", None) != "message-input":
            return
        text = event.value or ""
        try:
            bar = self.query_one("#suggest-bar", Static)
        except Exception:
            return
        if not text.startswith("/"):
            bar.add_class("hidden")
            return
        if self._commands is None:
            bar.add_class("hidden")
            return
        prefix = text.split()[0] if text.strip().split() else "/"
        # Only suggest on first token, hide after space with args
        if " " in text.strip():
            bar.add_class("hidden")
            return
        sug = self._commands.registry.suggest(prefix)
        if not sug:
            bar.add_class("hidden")
            return
        bar.update("  ".join(f"/{c.name}" for c in sug[:10]))
        bar.remove_class("hidden")

    def on_key(self, event) -> None:
        # Shift+Enter: insert newline for multiline input (Input is single-line
        # but value may contain \n for the LLM; we insert at cursor)
        is_shift_enter = (
            event.key in ("shift+enter", "enter")
            and "shift" in getattr(event, "modifiers", set())
        ) or event.key == "shift+enter"
        if is_shift_enter:
            try:
                inp = self.query_one("#message-input", Input)
            except Exception:
                return
            if not inp.has_focus:
                return
            val = inp.value or ""
            pos = getattr(inp, "cursor_position", len(val)) or 0
            # clamp
            pos = max(0, min(pos, len(val)))
            inp.value = val[:pos] + "\n" + val[pos:]
            inp.cursor_position = pos + 1
            event.prevent_default()
            event.stop()
            return
        # Up/Down: input history recall (prefix-filtered like fish/zsh)
        if event.key in ("up", "down"):
            try:
                inp = self.query_one("#message-input", Input)
            except Exception:
                return
            if not inp.has_focus or not self._input_history:
                return
            # use filtered list if active, else full history
            hist = self._history_filtered if self._history_filtered is not None else self._input_history
            if event.key == "up":
                if self._history_index == -1:
                    cur = inp.value or ""
                    self._history_draft = cur
                    if cur:
                        # prefix filter: only entries starting with current text
                        self._history_filtered = [h for h in self._input_history if h.startswith(cur)]
                        if not self._history_filtered:
                            self._history_filtered = None
                            return
                        hist = self._history_filtered
                    else:
                        self._history_filtered = None
                        hist = self._input_history
                    self._history_index = len(hist) - 1
                elif self._history_index > 0:
                    self._history_index -= 1
                else:
                    return
                inp.value = hist[self._history_index]
                inp.cursor_position = len(inp.value)
            else:  # down
                if self._history_index == -1:
                    return
                if self._history_index == len(hist) - 1:
                    self._history_index = -1
                    inp.value = self._history_draft
                    self._history_filtered = None
                else:
                    self._history_index += 1
                    inp.value = hist[self._history_index]
                inp.cursor_position = len(inp.value)
            event.prevent_default()
            event.stop()
            return
        # Tab autocomplete for slash commands
        if event.key != "tab":
            return
        try:
            inp = self.query_one("#message-input", Input)
        except Exception:
            return
        if not inp.has_focus:
            return
        text = inp.value or ""
        if not text.startswith("/"):
            return
        if " " in text.strip():
            return
        if self._commands is None:
            return
        prefix = text.split()[0] if text.strip().split() else "/"
        sug = self._commands.registry.suggest(prefix)
        if not sug:
            return
        # Complete with first match
        first = sug[0].name
        inp.value = f"/{first} "
        inp.cursor_position = len(inp.value)
        try:
            self.query_one("#suggest-bar", Static).add_class("hidden")
        except Exception:
            pass
        event.prevent_default()
        event.stop()

    def _handle_command(self, text: str) -> None:
        if self._commands is None:
            return
        result = self._commands.handle(text)
        if result.should_exit:
            self.exit()
            return
        if result.clear_history:
            self.conversation_history.clear()
            self.query_one("#chat-log", ChatLog).clear_log()
        if result.resumed_history is not None:
            self.conversation_history = result.resumed_history
            chat_log = self.query_one("#chat-log", ChatLog)
            chat_log.clear_log()
            for msg in self.conversation_history:
                if msg["role"] == "user":
                    chat_log.add_user(msg["content"])
                elif msg["role"] == "assistant":
                    chat_log.add_system(f"\\[Assistant]: {msg['content'][:200]}")
        if result.loaded_skill is not None:
            self.active_skill = result.loaded_skill
        if result.reload_sidebar:
            self._refresh_sidebar()
        if result.activate_tab:
            try:
                from textual.widgets import TabbedContent

                sidebar = self.query_one("#sidebar", Sidebar)
                sidebar.display = True
                tc = sidebar.query_one(TabbedContent)
                tc.active = f"tab-{result.activate_tab}"
            except Exception:
                pass
        if result.open_model_picker:
            self.push_screen(
                ModelPickerScreen(result.model_entries),
                callback=self._on_model_picker_result,
            )
            return
        if result.text:
            self.query_one("#chat-log", ChatLog).add_system(result.text)

    def _on_model_picker_result(self, result) -> None:
        """Callback after the model picker dismisses; performs the swap."""
        if not result:
            return
        provider = result.get("provider", "")
        model = result.get("model", "")
        if self._commands is None:
            return
        outcome = self._commands.switch_model(provider, model)
        if outcome.text:
            self.query_one("#chat-log", ChatLog).add_system(outcome.text)
        # The backend swap may have updated config.model/provider — refresh
        # the status bar so the new model shows immediately.
        self._update_status("ready")

    def _run_user_message(self, text: str) -> None:
        query = text
        if self.active_skill is not None:
            query = (
                f"[Active skill: {self.active_skill.name}]\n\n"
                f"{self.active_skill.content}\n\n---\n\nUser request: {text}"
            )
            self.active_skill = None

        self._current_query = query
        self._current_user_text = text
        self._current_history = list(self.conversation_history)
        self._pending_writes = None
        self._current_assistant_text = ""

        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.add_user(text)
        if self._session_logger is not None:
            self._session_logger.log_turn("user", text)

        self.query_one("#input-bar", InputBar).set_pending(True)
        self.query_one("#tool-panel", ToolPanel).clear_calls()

        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.add_thinking_indicator()

        runner = run_agent if self._thread_workers else run_agent_async
        self._agent_worker = self.run_worker(
            partial(runner, self, self._agent, query, history=self._current_history),
            thread=self._thread_workers,
            name="agent_run",
        )
        self._agent_worker_name = "agent_run"
        self._update_status("thinking")

    def on_agent_event(self, event: AgentEvent) -> None:
        chunk = event.event
        etype = chunk.get("type")
        chat_log = self.query_one("#chat-log", ChatLog)
        tool_panel = self.query_one("#tool-panel", ToolPanel)

        if etype == EventType.TEXT:
            chat_log.remove_thinking_indicator()
            self._current_assistant_text += chunk["content"]
            chat_log.append_text(chunk["content"])
        elif etype == EventType.THINKING:
            chat_log.remove_thinking_indicator()
            chat_log.append_thinking(chunk["content"])
        elif etype == EventType.TOOL_START:
            chat_log.remove_thinking_indicator()
            tool_panel.add_call(chunk["call_id"], chunk["name"], chunk.get("args", {}))
            self._update_status(f"tool: {chunk['name']}")
        elif etype == EventType.TOOL_RESULT:
            summary = chunk.get("summary", "")
            tool_panel.finish_call(
                chunk["call_id"],
                summary=summary,
                result=chunk.get("result"),
            )
            chat_log.add_tool_result(chunk["name"], summary)
        elif etype == EventType.TOOL_ERROR:
            error = chunk.get("error", "")
            tool_panel.finish_call(
                chunk["call_id"],
                error=error,
            )
            chat_log.add_tool_result(chunk["name"], f"Error: {error}")
        elif etype == EventType.ERROR:
            chat_log.add_system(f"[Error] {chunk.get('message', '')}")
        elif etype == EventType.CONFIRMATION_REQUIRED:
            self._pending_writes = chunk.get("pending_writes", [])
        elif etype == EventType.DONE:
            self._finalize_turn()

    def on_agent_done(self, event: AgentDone) -> None:
        self._agent_worker = None
        self._agent_worker_name = None
        self._finalize_turn()

    def on_agent_error(self, event: AgentError) -> None:
        self._agent_worker = None
        self._agent_worker_name = None
        self.query_one("#chat-log", ChatLog).add_system(f"[Error] {event.error}")
        self._finalize_turn()

    def _resolve_confirm(self) -> str:
        """Return the effective confirm-writes policy.

        Priority: session override > config > default "ask".
        """
        if self._session_confirm_writes is not None:
            return self._session_confirm_writes
        if self._config is not None:
            return self._config.get("auto_confirm_writes", "ask")
        return "ask"

    def _build_confirm_calls(self) -> list[ToolCall]:
        return [
            ToolCall(
                name=w["tool_name"],
                args=w.get("args", {}),
                call_id=w.get("call_id", f"confirm_{i}"),
                is_write=True,
            )
            for i, w in enumerate(self._pending_writes or [])
        ]

    def _execute_confirmed_writes(self) -> None:
        calls = self._build_confirm_calls()
        self._pending_writes = None
        if not calls:
            self.query_one("#input-bar", InputBar).set_pending(False)
            self._update_status("ready")
            return
        runner = run_agent if self._thread_workers else run_agent_async
        self._agent_worker = self.run_worker(
            partial(
                runner,
                self,
                self._agent,
                self._current_query,
                history=self._current_history,
                confirm=True,
                pending_tool_calls=calls,
            ),
            thread=self._thread_workers,
            name="agent_confirm",
        )
        self._agent_worker_name = "agent_confirm"
        self._update_status("confirming writes")

    def _cancel_pending_writes(self, reason: str = "cancelled by user") -> None:
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.add_system(f"Write operation {reason}.")
        self._pending_writes = None
        self.query_one("#input-bar", InputBar).set_pending(False)
        self._update_status("ready")

    def _finalize_turn(self) -> None:
        if self._pending_writes:
            # Guard against double-push: on_agent_event(DONE) and on_agent_done
            # both fire for the same run and would otherwise push two screens
            if isinstance(self.screen, ConfirmationScreen):
                return
            # previous worker is done
            self._agent_worker = None
            self._agent_worker_name = None
            policy = self._resolve_confirm()
            if policy == "allow":
                self._execute_confirmed_writes()
                return
            if policy == "deny":
                self._cancel_pending_writes("auto-denied by policy")
                return
            writes = self._pending_writes
            self.push_screen(ConfirmationScreen(writes), callback=self._on_confirm)
            return

        # no pending writes — turn complete, clear worker
        self._agent_worker = None
        self._agent_worker_name = None
        assistant_text = self._current_assistant_text
        self.conversation_history.append({"role": "user", "content": self._current_user_text})
        self.conversation_history.append({"role": "assistant", "content": assistant_text})
        if self._session_logger is not None:
            self._session_logger.log_turn("assistant", assistant_text)

        self._current_assistant_text = ""
        self.query_one("#input-bar", InputBar).set_pending(False)
        self._update_status("ready")
        self._refresh_sidebar()

    def _on_confirm(self, payload: dict | bool | None) -> None:
        # Dismiss payloads older than the current screen callback may pass a
        # bool; the new screen passes {"confirm": bool, "remember": bool}.
        if isinstance(payload, dict):
            confirmed = payload.get("confirm", False)
            remember = payload.get("remember", False)
        else:
            confirmed = bool(payload)
            remember = False

        if remember:
            self._session_confirm_writes = "allow" if confirmed else "deny"

        if not confirmed:
            reason = "cancelled by user" if not remember else "denied for session"
            self._cancel_pending_writes(reason)
            return

        self._execute_confirmed_writes()

    def action_clear_history(self) -> None:
        self.conversation_history.clear()
        self.query_one("#chat-log", ChatLog).clear_log()

    def action_focus_input(self) -> None:
        self.query_one("#message-input").focus()

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.display = not sidebar.display

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_history_search(self) -> None:
        if not self._input_history:
            self.query_one("#chat-log", ChatLog).add_system("No history yet.")
            return
        self.push_screen(
            HistorySearchScreen(self._input_history),
            callback=self._on_history_search_result,
        )

    def _on_history_search_result(self, result: str | None) -> None:
        if not result:
            return
        try:
            inp = self.query_one("#message-input", Input)
            inp.value = result
            inp.cursor_position = len(result)
            inp.focus()
        except Exception:
            pass

    def on_input_bar_stop_requested(self, event: InputBar.StopRequested) -> None:
        self.action_cancel_agent()

    def action_cancel_agent(self) -> None:
        # Let modal screens handle Esc themselves (decline/close)
        if isinstance(self.screen, ConfirmationScreen):
            return
        # Check if any modal is on top (help/model/history/detail/menu)
        if self.screen is not self.screen_stack[-1].screen if hasattr(self, "screen_stack") else False:
            pass  # not needed, modals handle their own Esc
        worker = getattr(self, "_agent_worker", None)
        if worker is None:
            return
        try:
            if hasattr(worker, "is_finished") and worker.is_finished:
                self._agent_worker = None
                return
            if hasattr(worker, "cancel"):
                worker.cancel()
        except Exception:
            pass
        self._agent_worker = None
        self._agent_worker_name = None
        try:
            chat = self.query_one("#chat-log", ChatLog)
            chat.remove_thinking_indicator()
            chat.add_system("Cancelled.")
        except Exception:
            pass
        try:
            self.query_one("#input-bar", InputBar).set_pending(False)
        except Exception:
            pass
        self._pending_writes = None
        self._update_status("ready")

    def on_unmount(self) -> None:
        if self._session_logger is not None:
            self._session_logger.end_session()

    def on_tool_panel_detail_requested(self, event: ToolPanel.DetailRequested) -> None:
        call = event.call
        lines = [f"# {call['name']}", ""]
        lines.append(f"**Status:** {call['status']}")
        import json
        lines.append(f"**Arguments:** `{json.dumps(call['args'], ensure_ascii=False)}`")
        if call["summary"]:
            lines.append(f"**Summary:** {call['summary']}")
        if call["result"] is not None:
            try:
                result_text = json.dumps(call["result"], ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                result_text = str(call["result"])
            lines.append(f"**Result:**\n```\n{result_text[:2000]}\n```")
        if call["error"]:
            lines.append(f"**Error:** {call['error']}")
        self.push_screen(_DetailScreen("\n".join(lines)))

    def on_sidebar_search_memory(self, event: Sidebar.SearchMemory) -> None:
        results = self._agent.search_memory(event.query, k=10)
        self.query_one("#sidebar", Sidebar).set_memories(results)

    def on_sidebar_add_memory(self, event: Sidebar.AddMemory) -> None:
        mid = self._agent.add_memory(event.text)
        self.query_one("#chat-log", ChatLog).add_system(f"Added memory: {mid}")
        self._refresh_sidebar()

    def on_sidebar_memory_selected(self, event: Sidebar.MemorySelected) -> None:
        text = getattr(event.memory, "text", str(event.memory))
        self.query_one("#chat-log", ChatLog).add_system(f"[Memory] {text}")

    def on_sidebar_search_knowledge(self, event: Sidebar.SearchKnowledge) -> None:
        knowledge_dir = Path(self._agent.context_dir) / "knowledge"
        docs = [{"title": p.name} for p in knowledge_dir.glob("*.md")]
        if event.query:
            docs = [d for d in docs if event.query.lower() in d["title"].lower()]
        self.query_one("#sidebar", Sidebar).set_knowledge(docs)

    def on_sidebar_knowledge_selected(self, event: Sidebar.KnowledgeSelected) -> None:
        title = getattr(event.doc, "title", str(event.doc))
        self.query_one("#chat-log", ChatLog).add_system(f"[Knowledge] {title}")

    def on_sidebar_skill_selected(self, event: Sidebar.SkillSelected) -> None:
        self.active_skill = event.skill
        self.query_one("#chat-log", ChatLog).add_system(
            f"Loaded skill: {event.skill.name} (will be included in next message)"
        )

    def on_sidebar_session_selected(self, event: Sidebar.SessionSelected) -> None:
        sid = event.session.get("id", "")
        resumed = self._session_logger.get_session_context(sid)
        if resumed:
            self.conversation_history = resumed
            chat_log = self.query_one("#chat-log", ChatLog)
            chat_log.clear_log()
            for msg in resumed:
                if msg["role"] == "user":
                    chat_log.add_user(msg["content"])
                elif msg["role"] == "assistant":
                    chat_log.add_system(f"\\[PROMPT_INJECTION]: {msg['content'][:200]}")
            chat_log.add_system(f"Resumed session {sid[:8]} ({len(resumed)} turns loaded).")
        else:
            self.query_one("#chat-log", ChatLog).add_system(f"Session '{sid[:8]}' not found.")

    def on_input_bar_menu_requested(self, _event: InputBar.MenuRequested) -> None:
        self.push_screen(_MenuScreen(self._menu_actions()))

    def _menu_actions(self):
        return [
            ("Help", lambda: self.push_screen(HelpScreen())),
            ("Reload skills", lambda: self._handle_command("/reload")),
            ("Unload model", lambda: self._handle_command("/unload")),
            ("Clear history", lambda: self._handle_command("/clear")),
            ("Quit", self.exit),
        ]

    def _refresh_sidebar(self) -> None:
        if self._agent is None:
            return
        sidebar = self.query_one("#sidebar", Sidebar)
        try:
            sidebar.set_memories(self._agent.list_memories(20))
        except Exception as exc:  # noqa: BLE001 - defensive sidebar refresh
            self.log(f"refresh memories failed: {exc}")
        try:
            knowledge_dir = Path(self._agent.context_dir) / "knowledge"
            docs = [{"title": p.name} for p in knowledge_dir.glob("*.md")]
            sidebar.set_knowledge(docs)
        except Exception as exc:  # noqa: BLE001 - defensive sidebar refresh
            self.log(f"refresh knowledge failed: {exc}")
        try:
            sidebar.set_skills([s for s in self._agent.skills.all() if s.procedure])
        except Exception as exc:  # noqa: BLE001 - defensive sidebar refresh
            self.log(f"refresh skills failed: {exc}")
        try:
            sidebar.set_sessions(self._session_logger.list_sessions(10))
        except Exception as exc:  # noqa: BLE001 - defensive sidebar refresh
            self.log(f"refresh sessions failed: {exc}")
        self._update_status("ready")

    def _update_status(self, status: str) -> None:
        if self._agent is None:
            return
        bar = self.query_one("#status-bar", StatusBar)
        try:
            memory_count = len(self._agent.memory)
        except Exception as exc:  # noqa: BLE001 - defensive status update
            self.log(f"memory count failed: {exc}")
            memory_count = 0
        try:
            knowledge_dir = Path(self._agent.context_dir) / "knowledge"
            knowledge_count = len(list(knowledge_dir.glob("*.md")))
        except Exception as exc:  # noqa: BLE001 - defensive status update
            self.log(f"knowledge count failed: {exc}")
            knowledge_count = 0
        try:
            skill_count = len([s for s in self._agent.skills.all() if s.procedure])
        except Exception as exc:  # noqa: BLE001 - defensive status update
            self.log(f"skill count failed: {exc}")
            skill_count = 0
        model = getattr(self._agent.config, "model", "") or ""
        provider = getattr(self._agent.config, "provider", "") or ""
        # model context window (n_ctx) and current window usage
        # Prefer live value from the running backend/model, then config
        n_ctx = None
        try:
            # 1. live backend (llamacpp knows its n_ctx)
            llm = getattr(self._agent, "llm", None)
            if llm is not None:
                if hasattr(llm, "_init_kwargs") and isinstance(llm._init_kwargs, dict):
                    n_ctx = llm._init_kwargs.get("n_ctx")
                if n_ctx is None and hasattr(llm, "n_ctx"):
                    n_ctx = getattr(llm, "n_ctx")
            # 2. catalog live fetch for current provider/model (openrouter/openai context_length)
            if n_ctx is None:
                try:
                    from micron.catalog import ModelCatalog

                    cat = ModelCatalog()
                    for e in cat.list(provider=provider):
                        if e.name == model and e.meta.get("context_length"):
                            n_ctx = int(e.meta["context_length"])
                            break
                except Exception:
                    pass
            # 3. config (agent llm_kwargs / provider config)
            if n_ctx is None:
                n_ctx = getattr(self._agent.config, "n_ctx", None)
                if n_ctx is None:
                    n_ctx = self._agent.config.llm_kwargs.get("n_ctx")  # type: ignore[attr-defined]
            if n_ctx is not None:
                n_ctx = int(n_ctx)
        except Exception:
            n_ctx = None
        if n_ctx is None:
            try:
                from micron.config import Config

                n_ctx = Config().runtime(provider_override=provider).n_ctx
            except Exception:
                n_ctx = None
        history_len = len(self.conversation_history) if isinstance(self.conversation_history, list) else 0
        bar.update_status(
            session_id=self._session_id,
            provider=provider,
            model=model,
            memory_count=memory_count,
            knowledge_count=knowledge_count,
            skill_count=skill_count,
            status=status,
            n_ctx=n_ctx,
            history_len=history_len,
        )


class _DetailScreen(Screen):
    """Popup detail view for a tool result."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "dismiss", "Close")]

    def __init__(self, markdown: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._markdown = markdown

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-dialog"):
            yield Markdown(self._markdown)
            yield Button("Close", id="detail-close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "detail-close":
            self.dismiss()


class _MenuScreen(Screen):
    """Popup menu for common actions."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "dismiss", "Close")]

    def __init__(self, actions: list[tuple[str, Callable]], **kwargs) -> None:
        super().__init__(**kwargs)
        self._actions = actions

    def compose(self) -> ComposeResult:
        with Vertical(id="menu-dialog"):
            for i, (label, _) in enumerate(self._actions):
                yield Button(label, id=f"menu-{i}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id and btn_id.startswith("menu-"):
            idx = int(btn_id.split("-", 1)[1])
            callback = self._actions[idx][1]
            callback()
            self.dismiss()
