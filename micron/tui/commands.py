"""Slash command dispatcher for micron TUI."""
from __future__ import annotations

from textual.message import Message


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
    """Handles /commands for the TUI."""

    def __init__(self, app, agent, logger, config: dict):
        self.app = app
        self.agent = agent
        self.logger = logger
        self.config = config

    def handle(self, cmd: str) -> CommandResult:
        parts = cmd[1:].strip().split()
        if not parts:
            return CommandResult(text="Empty command.")
        command = parts[0].lower()
        args = parts[1:]

        if command in ("exit", "quit", "q"):
            return CommandResult(should_exit=True)

        if command in ("help", "?", "h"):
            return CommandResult(text=self._help_text())

        if command == "clear":
            return CommandResult(clear_history=True)

        if command == "mem":
            return CommandResult(text=self._memories(), reload_sidebar=True)

        if command == "tools":
            return CommandResult(text=self._tools())

        if command == "model":
            return CommandResult(text=self._model())

        if command == "providers":
            return CommandResult(text=self._providers())

        if command == "unload":
            self.agent.unload_model()
            return CommandResult(text="Model unloaded from memory.")

        if command == "reload":
            before = len(self.agent.skills.all())
            self.agent.reload_skills()
            after = len(self.agent.skills.all())
            return CommandResult(text=f"Skills reloaded ({before} → {after}).", reload_sidebar=True)

        if command == "sessions":
            return CommandResult(text=self._sessions(), reload_sidebar=True)

        if command == "resume":
            return self._resume(args)

        if command == "last":
            return self._last()

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

        if command == "skill":
            return self._skill(args)

        if command == "skills":
            return CommandResult(text=self._skills())

        return CommandResult(text=f"Unknown command: {command}. Try /help")

    @staticmethod
    def _help_text() -> str:
        return (
            "Commands:\n"
            "  /help, /?    Show this help\n"
            "  /exit, /quit Exit\n"
            "  /clear       Clear conversation history\n"
            "  /mem         List recent memories\n"
            "  /tools       Show available tools\n"
            "  /model       Show current model info\n"
            "  /providers   List configured providers\n"
            "  /unload      Unload model from RAM\n"
            "  /reload      Reload skills from disk\n"
            "  /sessions    List recent sessions\n"
            "  /resume ID   Resume a previous session\n"
            "  /last        Show last assistant response\n"
            "  /trash       List deleted files\n"
            "  /restore F   Restore file from trash\n"
            "  /purge       Empty trash permanently\n"
            "  /undo F      Restore from .bak backup\n"
            "  /tree        Show directory tree\n"
            "  /skill NAME  Load a procedure skill\n"
            "  /skills      List procedure skills"
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
        from micron.__main__ import load_config
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

    def _sessions(self) -> str:
        sessions = self.logger.list_sessions(10)
        if not sessions:
            return "No sessions found."
        lines = ["Recent sessions:"]
        for s in sessions:
            lines.append(f"  {s['id']}  {s['turns']} turns  {s['size'] // 1024}KB")
        return "\n".join(lines)

    def _resume(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(text="Usage: /resume <session_id>")
        resumed = self.logger.get_session_context(args[0])
        if not resumed:
            return CommandResult(text=f"Session '{args[0]}' not found.")
        return CommandResult(
            text=f"Resumed session {args[0]} ({len(resumed)} turns loaded).",
            resumed_history=resumed,
        )

    def _last(self) -> CommandResult:
        history = self.app.conversation_history
        if not history:
            return CommandResult(text="No messages yet.")
        last_msg = history[-1]
        return CommandResult(text=f"[{last_msg['role']}]: {last_msg['content'][:500]}")

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

    def _skill(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(text="Usage: /skill <name>")
        found = self.agent.skills.get(args[0])
        if not found:
            return CommandResult(text=f"Skill '{args[0]}' not found.")
        if not found.procedure:
            return CommandResult(text=f"'{args[0]}' is a tool skill, not a procedure skill.")
        return CommandResult(
            text=f"Loaded: {found.name}\nDescription: {found.description}\nContent: {len(found.content)} chars",
            loaded_skill=found,
        )

    def _skills(self) -> str:
        procedures = [s for s in self.agent.skills.all() if s.procedure]
        if not procedures:
            return "No procedure skills loaded."
        lines = [f"Procedure skills ({len(procedures)}):"]
        for s in procedures:
            lines.append(f"  {s.name:30s} {s.description[:60]}")
        return "\n".join(lines)
