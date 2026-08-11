"""Slash command dispatcher for micron TUI.

The read-only batch (/help, /clear, /mem, /tools, /model, /providers)
and the session-management batch (/unload, /reload, /sessions, /resume,
/last, /skill, /skills) are handled by
:class:`micron.slash.SlashCommandRegistry`. The remaining file-recovery
commands and /exit still live in the if/elif block.

When all commands have migrated, the if/elif block disappears (issue
#4). The contract step.
"""
from __future__ import annotations

from textual.message import Message

from micron.slash import SlashCommandRegistry, SlashCommandResult


class CommandResult(Message):
    """Posted by CommandDispatcher after handling a command."""

    def __init__(
        self,
        *,
        text: str = "",
        clear_history: bool = False,
        reload_sidebar: bool = False,
        loaded_skill=None,
        resumed_history: list[dict] | None = None,
        should_exit: bool = False,
    ) -> None:
        super().__init__()
        self.text = text
        self.clear_history = clear_history
        self.reload_sidebar = reload_sidebar
        self.loaded_skill = loaded_skill
        self.resumed_history = resumed_history
        self.should_exit = should_exit


class CommandDispatcher:
    """Handles /commands for the TUI.

    Read-only + session-management commands go through ``self.registry``;
    file-recovery commands and /exit still through the if/elif ladder.
    Once all commands migrate, the ladder disappears (issue #4).
    """

    def __init__(self, app, agent, logger, config: dict):
        self.app = app
        self.agent = agent
        self.logger = logger
        self.config = config
        self.registry = SlashCommandRegistry()
        self._register_readonly_commands()
        self._register_session_commands()

    def _register_readonly_commands(self) -> None:
        """Register /help, /clear, /mem, /tools, /model, /providers."""
        reg = self.registry

        @reg.register("help", aliases=("?", "h"), help_text="Show this help")
        def _help(args: list[str]) -> SlashCommandResult:
            return SlashCommandResult(text=self._help_text())

        @reg.register("clear", help_text="Clear conversation history")
        def _clear(args: list[str]) -> SlashCommandResult:
            return SlashCommandResult(extras={"clear_history": True})

        @reg.register("mem", help_text="List recent memories")
        def _mem(args: list[str]) -> SlashCommandResult:
            return SlashCommandResult(
                text=self._memories(),
                extras={"reload_sidebar": True},
            )

        @reg.register("tools", help_text="Show available tools")
        def _tools(args: list[str]) -> SlashCommandResult:
            return SlashCommandResult(text=self._tools())

        @reg.register("model", help_text="Show current model info")
        def _model(args: list[str]) -> SlashCommandResult:
            return SlashCommandResult(text=self._model())

        @reg.register("providers", help_text="List configured providers")
        def _providers(args: list[str]) -> SlashCommandResult:
            return SlashCommandResult(text=self._providers())

    def _register_session_commands(self) -> None:
        """Register /unload, /reload, /sessions, /resume, /last, /skill, /skills."""
        reg = self.registry

        @reg.register("unload", help_text="Unload model from RAM")
        def _unload(args: list[str]) -> SlashCommandResult:
            self.agent.unload_model()
            return SlashCommandResult(text="Model unloaded from memory.")

        @reg.register("reload", help_text="Reload skills from disk")
        def _reload(args: list[str]) -> SlashCommandResult:
            before = len(self.agent.skills.all())
            self.agent.reload_skills()
            after = len(self.agent.skills.all())
            return SlashCommandResult(
                text=f"Skills reloaded ({before} → {after}).",
                extras={"reload_sidebar": True},
            )

        @reg.register("sessions", help_text="List recent sessions")
        def _sessions(args: list[str]) -> SlashCommandResult:
            return SlashCommandResult(
                text=self._sessions_text(),
                extras={"reload_sidebar": True},
            )

        @reg.register("resume", help_text="Resume a previous session")
        def _resume(args: list[str]) -> SlashCommandResult:
            if not args:
                return SlashCommandResult(text="Usage: /resume <session_id>")
            resumed = self.logger.get_session_context(args[0])
            if not resumed:
                return SlashCommandResult(text=f"Session '{args[0]}' not found.")
            return SlashCommandResult(
                text=f"Resumed session {args[0]} ({len(resumed)} turns loaded).",
                extras={"resumed_history": resumed},
            )

        @reg.register("last", help_text="Show last assistant response")
        def _last(args: list[str]) -> SlashCommandResult:
            history = self.app.conversation_history
            if not history:
                return SlashCommandResult(text="No messages yet.")
            last_msg = history[-1]
            return SlashCommandResult(
                text=f"[{last_msg['role']}]: {last_msg['content'][:500]}"
            )

        @reg.register("skill", help_text="Load a procedure skill")
        def _skill(args: list[str]) -> SlashCommandResult:
            if not args:
                return SlashCommandResult(text="Usage: /skill <name>")
            found = self.agent.skills.get(args[0])
            if not found:
                return SlashCommandResult(text=f"Skill '{args[0]}' not found.")
            if not found.procedure:
                return SlashCommandResult(
                    text=f"'{args[0]}' is a tool skill, not a procedure skill."
                )
            return SlashCommandResult(
                text=(
                    f"Loaded: {found.name}\n"
                    f"Description: {found.description}\n"
                    f"Content: {len(found.content)} chars"
                ),
                extras={"loaded_skill": found},
            )

        @reg.register("skills", help_text="List procedure skills")
        def _skills(args: list[str]) -> SlashCommandResult:
            return SlashCommandResult(text=self._skills_text())

    def handle(self, cmd: str) -> CommandResult:
        parts = cmd[1:].strip().split()
        if not parts:
            return CommandResult(text="Empty command.")
        command = parts[0].lower()
        args = parts[1:]

        # Migrated commands — registry handles them.
        if self.registry.get(command) is not None:
            result = self.registry.dispatch(cmd)
            return CommandResult(
                text=result.text,
                clear_history=result.extras.get("clear_history", False),
                reload_sidebar=result.extras.get("reload_sidebar", False),
                loaded_skill=result.extras.get("loaded_skill"),
                resumed_history=result.extras.get("resumed_history"),
                should_exit=result.extras.get("should_exit", False),
            )

        # Unmigrated commands — original if/elif ladder.
        if command in ("exit", "quit", "q"):
            return CommandResult(should_exit=True)

        if command == "trash":
            from micron.tools.builtin import list_trash
            return CommandResult(text=str(list_trash()))

        if command == "restore":
            if not args:
                return CommandResult(text="Usage: /restore <filename>")
            from micron.tools.builtin import restore_file
            return CommandResult(text=str(restore_file(args[0])))

        if command == "purge":
            from micron.tools.builtin import purge_trash
            return CommandResult(text=str(purge_trash()))

        if command == "undo":
            if not args:
                return CommandResult(text="Usage: /undo <filename>")
            from micron.tools.builtin import undo_file
            return CommandResult(text=str(undo_file(args[0])))

        if command == "tree":
            return CommandResult(text=self._tree(args))

        return CommandResult(text=f"Unknown command: {command}. Try /help")

    def _help_text(self) -> str:
        # Show registry commands (auto-generated) plus the unmigrated
        # ones, so /help still describes everything the user can type.
        return "\n".join(
            [
                self.registry.help_text(),
                "  /exit, /quit   Exit",
                "  /trash         List deleted files",
                "  /restore F     Restore file from trash",
                "  /purge         Empty trash permanently",
                "  /undo F        Restore from .bak backup",
                "  /tree          Show directory tree",
            ]
        )

    def _memories(self) -> str:
        memories = self.agent.list_memories(10)
        if not memories:
            return "No memories stored."
        lines = [f"Recent memories ({len(memories)}):"]
        for m in memories:
            tags = " ".join(f"#{t}" for t in m.tags) if getattr(m, "tags", None) else ""
            lines.append(f"  [{m.id[:8]}] {m.text[:80]} {tags}")
        return "\n".join(lines)

    def _tools(self) -> str:
        tools = self.agent.tools.list()
        if not tools:
            return "No tools available."
        lines = [f"Available tools ({len(tools)}):"]
        for t in tools:
            write_tag = " [write]" if t.get("write", False) else ""
            lines.append(f"  {t['name']}: {t['description']}{write_tag}")
        return "\n".join(lines)

    def _model(self) -> str:
        llm = self.agent.llm
        lines = [f"Provider: {llm.__class__.__name__}"]
        if hasattr(llm, "_init_kwargs"):
            import json
            lines.append(json.dumps(llm._init_kwargs, indent=2, default=str))
        return "\n".join(lines)

    def _providers(self) -> str:
        from micron.config import load_config
        cfg = load_config()
        providers = cfg.get("providers", {})
        default = cfg.get("default_provider", "llamacpp")
        import os
        active = os.environ.get("MICRON_PROVIDER", default)
        lines = [f"Default: {default}  Active: {active}"]
        for name, prov_cfg in providers.items():
            model = prov_cfg.get("model", "(no model set)")
            marker = " ← active" if name == active else ""
            lines.append(f"  {name}: {model}{marker}")
        return "\n".join(lines)

    def _sessions_text(self) -> str:
        sessions = self.logger.list_sessions(10)
        if not sessions:
            return "No sessions found."
        lines = ["Recent sessions:"]
        for s in sessions:
            lines.append(f"  {s['id']}  {s['turns']} turns  {s['size'] // 1024}KB")
        return "\n".join(lines)

    def _tree(self, args: list[str]) -> str:
        from micron.tools.builtin import tree
        max_depth = 3
        ext = None
        tree_path = "."
        for arg in args:
            if arg.startswith("--depth="):
                max_depth = int(arg.split("=", 1)[1])
            elif arg.startswith("--ext="):
                ext = arg.split("=", 1)[1]
            else:
                tree_path = arg
        return str(tree(tree_path, max_depth=max_depth, ext=ext))

    def _skills_text(self) -> str:
        procedures = [s for s in self.agent.skills.all() if s.procedure]
        if not procedures:
            return "No procedure skills loaded."
        lines = [f"Procedure skills ({len(procedures)}):"]
        for s in procedures:
            lines.append(f"  {s.name:30s} {s.description[:60]}")
        return "\n".join(lines)