"""Tests for the micron Textual TUI."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest
from textual.widgets import Input

from micron.tui.app import MicronTUI
from micron.tui.screens.confirm import ConfirmationScreen
from micron.tui.screens.models import ModelPickerScreen
from micron.tui.widgets.chat import ChatLog
from micron.tui.widgets.input_bar import InputBar
from micron.tui.widgets.sidebar import Sidebar
from micron.tui.widgets.status_bar import StatusBar
from micron.tui.widgets.tool_panel import ToolPanel


class FakeMemory:
    def __init__(self, mid, text, tags=None):
        self.id = mid
        self.text = text
        self.tags = tags or []


class FakeSkill:
    def __init__(self, name, description, procedure=True, content=""):
        self.name = name
        self.description = description
        self.procedure = procedure
        self.content = content


class FakeSkills:
    def __init__(self):
        self._skills = [FakeSkill("test", "A test skill", content="skill body")]

    def all(self):
        return self._skills

    def get(self, name):
        for s in self._skills:
            if s.name == name:
                return s
        return None


class FakeTools:
    def __init__(self):
        self._tools = [{"name": "write_file", "description": "Write a file", "write": True}]

    def list(self):
        return self._tools

    def schemas(self):
        return []

    def is_write(self, name):
        return any(t["name"] == name and t.get("write") for t in self._tools)


class FakeLLM:
    _init_kwargs: ClassVar[dict] = {"model": "fake"}


class FakeAgent:
    def __init__(self, tmp_path: Path):
        self.context_dir = tmp_path / "context"
        self.context_dir.mkdir(parents=True, exist_ok=True)
        (self.context_dir / "knowledge").mkdir(exist_ok=True)
        self.memory = FakeMemoryStore()
        self.skills = FakeSkills()
        self.tools = FakeTools()
        self.llm = FakeLLM()
        self.config = type("Config", (), {"provider": "fake", "model": "fake-model"})()
        self._events = []

    def run(self, message, history=None, stream=True, confirm=False, pending_tool_calls=None):
        if confirm and pending_tool_calls:
            for tc in pending_tool_calls:
                yield {"type": "tool_result", "name": tc.name, "call_id": tc.call_id, "summary": "done"}
            yield {"type": "done"}
            return
        yield from self._events
        yield {"type": "done"}

    def list_memories(self, n=20):
        return self.memory.list(n=n)

    def search_memory(self, query, k=5):
        return self.memory.search(query, k=k)

    def add_memory(self, text, tags=None, importance=3):
        return self.memory.add(text, tags=tags, importance=importance)

    def unload_model(self):
        pass

    def reload_skills(self):
        pass


class FakeMemoryStore:
    def __init__(self):
        self._memories = [FakeMemory("m1", "hello world")]

    def __len__(self):
        return len(self._memories)

    def list(self, n=20):
        return self._memories[:n]

    def search(self, query, k=5):
        return [m for m in self._memories if query.lower() in m.text.lower()][:k]

    def add(self, text, tags=None, importance=3):
        m = FakeMemory(f"m{len(self._memories) + 1}", text, tags)
        self._memories.append(m)
        return m.id


class FakeLogger:
    def __init__(self, tmp_path: Path):
        self._sessions = []
        self._turns = []
        self._path = tmp_path / "sessions"
        self._path.mkdir(parents=True, exist_ok=True)

    def start_session(self):
        sid = "abc123"
        self._sessions.append({"id": sid, "turns": 0, "size": 0})
        return sid

    def end_session(self):
        pass

    def log_turn(self, role, content):
        self._turns.append({"role": role, "content": content})

    def list_sessions(self, n=10):
        return self._sessions[:n]

    def get_session_context(self, sid):
        if sid == "abc123":
            return [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        return []


def make_factory(tmp_path: Path):
    def factory():
        agent = FakeAgent(tmp_path)
        logger = FakeLogger(tmp_path)
        sid = logger.start_session()
        return agent, logger, sid
    return factory


@pytest.mark.asyncio
async def test_app_mounts(tmp_path):
    app = MicronTUI(make_factory(tmp_path), thread_workers=False)
    async with app.run_test():
        assert app.query_one("#chat-log", ChatLog) is not None
        assert app.query_one("#tool-panel", ToolPanel) is not None
        assert app.query_one("#sidebar", Sidebar) is not None
        assert app.query_one("#input-bar", InputBar) is not None
        assert app.query_one("#status-bar", StatusBar) is not None


@pytest.mark.asyncio
async def test_submit_message(tmp_path):
    app = MicronTUI(make_factory(tmp_path), thread_workers=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.query_one("#message-input", Input).value = "hello"
        await pilot.click("#send-btn")
        await pilot.pause()
        await asyncio.sleep(0.3)
        await pilot.pause()
        chat_log = app.query_one("#chat-log", ChatLog)
        # The user message should be rendered
        assert len(list(chat_log.children)) >= 1


@pytest.mark.asyncio
async def test_clear_command(tmp_path):
    app = MicronTUI(make_factory(tmp_path), thread_workers=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.query_one("#message-input", Input).value = "/clear"
        await pilot.click("#send-btn")
        await pilot.pause()
        chat_log = app.query_one("#chat-log", ChatLog)
        assert len(list(chat_log.children)) == 0


@pytest.mark.asyncio
async def test_tool_events_update_panel(tmp_path):
    app = MicronTUI(make_factory(tmp_path), thread_workers=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._agent, app._session_logger, app._session_id = make_factory(tmp_path)()
        app._agent._events = [
            {"type": "tool_start", "name": "write_file", "call_id": "c1"},
            {"type": "tool_result", "name": "write_file", "call_id": "c1", "summary": "ok"},
            {"type": "done"},
        ]
        tool_panel = app.query_one("#tool-panel", ToolPanel)
        assert len(tool_panel.calls) == 0
        input_bar = app.query_one("#input-bar", InputBar)
        input_bar.query_one("#message-input", Input).value = "write something"
        await pilot.click("#send-btn")
        await pilot.pause()
        await asyncio.sleep(0.3)
        await pilot.pause()
        # Tool start/result should be recorded
        assert any(c["call_id"] == "c1" for c in tool_panel.calls)


@pytest.mark.asyncio
async def test_confirmation_screen_default_no(tmp_path):
    app = MicronTUI(make_factory(tmp_path), thread_workers=False)
    screen = ConfirmationScreen([{"tool_name": "write_file", "args": {"path": "foo.txt"}, "call_id": "c1"}])
    async with app.run_test() as pilot:
        app.push_screen(screen)
        await pilot.pause()
        focused = app.focused
        assert focused is not None
        assert focused.id == "confirm-no"


def test_confirmation_screen_summary(tmp_path):
    """Summary line is compact and includes all operations."""
    app = MicronTUI(make_factory(tmp_path), thread_workers=False)
    writes = [
        {"tool_name": "write_file", "args": {"path": "foo.txt"}, "call_id": "c1"},
        {"tool_name": "edit_file", "args": {"path": "bar.py"}, "call_id": "c2"},
        {"tool_name": "run_command", "args": {"cmd": "ls -la"}, "call_id": "c3"},
    ]
    screen = ConfirmationScreen(writes)
    summary = screen._summarize()
    assert "3 write operations" in summary
    assert "write foo.txt" in summary
    assert "edit bar.py" in summary
    assert "run ls -la" in summary


def test_resolve_confirm_defaults(tmp_path):
    """No config, no session override -> 'ask'."""
    app = MicronTUI(make_factory(tmp_path), thread_workers=False, config=None)
    assert app._resolve_confirm() == "ask"


def test_resolve_confirm_config_allow(tmp_path):
    """Config auto_confirm_writes: allow is respected."""
    cfg = {"auto_confirm_writes": "allow"}
    app = MicronTUI(make_factory(tmp_path), thread_workers=False, config=cfg)
    assert app._resolve_confirm() == "allow"


def test_resolve_confirm_session_override(tmp_path):
    """Session override wins over config."""
    cfg = {"auto_confirm_writes": "deny"}
    app = MicronTUI(make_factory(tmp_path), thread_workers=False, config=cfg)
    app._session_confirm_writes = "allow"
    assert app._resolve_confirm() == "allow"


@pytest.mark.asyncio
async def test_on_confirm_remember_sets_session(tmp_path):
    """_on_confirm with remember=True sets session override to allow."""
    app = MicronTUI(make_factory(tmp_path), thread_workers=False, config=None)
    async with app.run_test():
        app._pending_writes = [{"tool_name": "write_file", "args": {"path": "x"}, "call_id": "c1"}]
        with patch.object(app, "_execute_confirmed_writes"):
            app._on_confirm({"confirm": True, "remember": True})
        assert app._session_confirm_writes == "allow"


@pytest.mark.asyncio
async def test_on_confirm_deny_remember_sets_deny(tmp_path):
    """_on_confirm with confirm=False + remember sets session to deny."""
    app = MicronTUI(make_factory(tmp_path), thread_workers=False, config=None)
    async with app.run_test():
        app._pending_writes = [{"tool_name": "write_file", "args": {"path": "x"}, "call_id": "c1"}]
        app._on_confirm({"confirm": False, "remember": True})
        assert app._session_confirm_writes == "deny"


@pytest.mark.asyncio
async def test_models_opens_picker_and_switches(tmp_path):
    """/models opens the picker; selecting a row swaps backend + status bar."""
    app = MicronTUI(make_factory(tmp_path), thread_workers=False)
    async with app.run_test() as pilot:
        await pilot.pause()

        class Commands:
            def __init__(self):
                self.switched = []

            def handle(self, text):
                from micron.tui.commands import CommandResult
                return CommandResult(
                    open_model_picker=True,
                    model_entries=[
                        ("ollama", "llama3", {}),
                        ("openrouter", "gpt-x", {"context_length": 128000}),
                    ],
                )

            def switch_model(self, provider, model):
                self.switched.append((provider, model))
                return type("R", (), {"text": f"Switched to {provider}/{model}."})()

        app._commands = Commands()
        app._handle_command("/models")
        await pilot.pause()

        assert isinstance(app.screen, ModelPickerScreen)
        assert app.screen._entries[1] == ("openrouter", "gpt-x", {"context_length": 128000})

        # Select the first row → switch runs, picker dismisses.
        from textual.widgets import ListView
        lv = app.screen.query_one("#model-list", ListView)
        lv.index = 0
        lv.action_select_cursor()
        await pilot.pause()

        assert app._commands.switched == [("ollama", "llama3")]
        assert not isinstance(app.screen, ModelPickerScreen)
