"""Tests for the SlashCommandRegistry (micron/slash.py) and the read-only
batch in micron/tui/commands.py."""
from __future__ import annotations

import pytest

from micron.slash import SlashCommandRegistry, SlashCommandResult


class TestSlashCommandRegistry:
    def test_register_and_dispatch_decorator(self):
        reg = SlashCommandRegistry()

        @reg.register("hello", help_text="Say hi")
        def _hello(args):
            return SlashCommandResult(text=f"hi {args[0] if args else 'world'}")

        result = reg.dispatch("/hello")
        assert result.text == "hi world"

        result = reg.dispatch("/hello there")
        assert result.text == "hi there"

    def test_register_and_dispatch_imperative(self):
        reg = SlashCommandRegistry()
        reg.add("ping", lambda args: SlashCommandResult(text="pong"), help_text="Ping")
        assert reg.dispatch("/ping").text == "pong"

    def test_aliases(self):
        reg = SlashCommandRegistry()
        reg.add("quit", lambda args: SlashCommandResult(text="bye"), aliases=("exit", "q"))

        assert reg.dispatch("/quit").text == "bye"
        assert reg.dispatch("/exit").text == "bye"
        assert reg.dispatch("/q").text == "bye"

        # all() should not duplicate the shared command
        names = [c.name for c in reg.all()]
        assert names == ["quit"]

    def test_unknown_command(self):
        reg = SlashCommandRegistry()
        result = reg.dispatch("/nope")
        assert "Unknown command" in result.text
        assert "nope" in result.text

    def test_empty_command(self):
        reg = SlashCommandRegistry()
        result = reg.dispatch("")
        assert "Empty" in result.text

    def test_non_slash_prefix(self):
        reg = SlashCommandRegistry()
        result = reg.dispatch("hello")
        assert "must start with /" in result.text

    def test_help_text_auto_generated(self):
        reg = SlashCommandRegistry()

        @reg.register("foo", help_text="Do foo")
        def _foo(args):
            return SlashCommandResult()

        @reg.register("bar", help_text="Do bar", aliases=("b",))
        def _bar(args):
            return SlashCommandResult()

        text = reg.help_text()
        assert "Do foo" in text
        assert "Do bar" in text
        assert "/foo" in text
        assert "/bar" in text
        assert "/b" in text  # alias shown

    def test_get_returns_command(self):
        reg = SlashCommandRegistry()

        @reg.register("xyz", help_text="x")
        def _xyz(args):
            return SlashCommandResult()

        assert reg.get("xyz") is not None
        assert reg.get("xyz").name == "xyz"
        assert reg.get("missing") is None

    def test_handler_can_return_none(self):
        reg = SlashCommandRegistry()

        @reg.register("silent")
        def _silent(args):
            return None

        result = reg.dispatch("/silent")
        assert isinstance(result, SlashCommandResult)
        assert result.text == ""

    def test_extras_dict_carries_flags(self):
        reg = SlashCommandRegistry()

        @reg.register("flag")
        def _flag(args):
            return SlashCommandResult(text="ok", extras={"clear_history": True})

        result = reg.dispatch("/flag")
        assert result.extras == {"clear_history": True}


class TestCommandDispatcherReadOnlyMigration:
    """Verify the read-only batch routes through the registry and preserves
    CommandResult semantics (clear_history, reload_sidebar flags)."""

    def _make_dispatcher(self):
        from micron.tui.commands import CommandDispatcher

        class FakeApp:
            conversation_history: list = []

        class FakeAgent:
            class FakeLLM:
                pass

            llm = FakeLLM()

            def list_memories(self, n):
                return []

            class FakeTools:
                def list(self):
                    return []
            tools = FakeTools()

        class FakeLogger:
            def list_sessions(self, n):
                return []

        app = FakeApp()
        agent = FakeAgent()
        logger = FakeLogger()
        return CommandDispatcher(app, agent, logger, {})

    def test_clear_sets_clear_history_flag(self):
        d = self._make_dispatcher()
        result = d.handle("/clear")
        assert result.text == ""
        assert result.clear_history is True
        assert result.reload_sidebar is False

    def test_mem_sets_reload_sidebar(self):
        d = self._make_dispatcher()
        result = d.handle("/mem")
        assert "No memories stored" in result.text
        assert result.reload_sidebar is True

    def test_tools_returns_empty_message(self):
        d = self._make_dispatcher()
        result = d.handle("/tools")
        assert "No tools available" in result.text

    def test_unknown_still_falls_through(self):
        d = self._make_dispatcher()
        result = d.handle("/not_a_real_command")
        assert "Unknown command" in result.text

    def test_unmigrated_unload_still_works(self):
        """Confirm unmigrated commands still hit the if/elif ladder."""
        unloaded = []
        d = self._make_dispatcher()

        # Patch unload_model on the fake agent
        d.agent.unload_model = lambda: unloaded.append(True)
        result = d.handle("/unload")
        assert unloaded == [True]
        assert "unloaded" in result.text.lower()

    def test_help_lists_everything(self):
        """Auto-generated registry help should be merged into the dispatcher help."""
        d = self._make_dispatcher()
        result = d.handle("/help")
        # registry-migrated
        assert "/help" in result.text
        assert "/clear" in result.text
        assert "/mem" in result.text
        assert "/tools" in result.text
        assert "/model" in result.text
        assert "/providers" in result.text
        # unmigrated
        assert "/unload" in result.text
        assert "/trash" in result.text
        assert "/skill" in result.text

    def test_help_aliases_work(self):
        d = self._make_dispatcher()
        result = d.handle("/?")
        assert "/help" in result.text

    def test_registry_separate_from_dispatcher(self):
        """SlashCommandRegistry is transport-agnostic and can be used standalone."""
        reg = SlashCommandRegistry()

        @reg.register("echo", help_text="Repeat args")
        def _echo(args):
            return SlashCommandResult(text=" ".join(args))

        result = reg.dispatch("/echo hello world")
        assert result.text == "hello world"