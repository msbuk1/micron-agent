"""Slash command dispatcher for micron TUI.

Every /command the TUI understands is registered in a
:class:`micron.slash.SlashCommandRegistry`; :meth:`CommandDispatcher.handle`
is now a thin translation layer that dispatches to the registry and maps
the transport-agnostic :class:`SlashCommandResult` onto the Textual
:class:`CommandResult` message. There is no if/elif ladder left.
"""
from __future__ import annotations

from textual.message import Message

from micron.catalog import ModelCatalog
from micron.slash import SlashCommandRegistry, SlashCommandResult


def _format_price(raw) -> str:
    """Format a per-token USD price as dollars per million tokens.

    OpenRouter reports prices as string USD per token, e.g. ``"7.5e-08"``.
    Providers quote per-million-token rates, so we scale by 1e6 and strip
    trailing zeros: ``"7.5e-08"`` → ``"0.075"``.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    per_m = value * 1e6
    if per_m == 0:
        return "0"
    text = f"{per_m:.6f}".rstrip("0").rstrip(".")
    return text or "0"


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
        open_model_picker: bool = False,
        model_entries: list | None = None,
    ) -> None:
        super().__init__()
        self.text = text
        self.clear_history = clear_history
        self.reload_sidebar = reload_sidebar
        self.loaded_skill = loaded_skill
        self.resumed_history = resumed_history
        self.should_exit = should_exit
        self.open_model_picker = open_model_picker
        self.model_entries = model_entries or []


class CommandDispatcher:
    """Handles /commands for the TUI.

    All commands live in ``self.registry``; :meth:`handle` translates a
    :class:`SlashCommandResult` into a :class:`CommandResult`.
    """

    def __init__(self, app, agent, logger, config: dict, *, catalog: ModelCatalog | None = None):
        self.app = app
        self.agent = agent
        self.logger = logger
        self.config = config
        self.registry = SlashCommandRegistry()
        self.catalog = catalog or ModelCatalog()
        self._last_models: list = []
        self._register_readonly_commands()
        self._register_session_commands()
        self._register_file_commands()
        self._register_model_commands()
        self._register_memory_commands()

    def _register_readonly_commands(self) -> None:
        """Register /help, /clear, /mem, /tools, /providers."""
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

    def _register_file_commands(self) -> None:
        """Register /exit, /trash, /restore, /purge, /undo, /tree."""
        reg = self.registry

        @reg.register("exit", aliases=("quit", "q"), help_text="Exit")
        def _exit(args: list[str]) -> SlashCommandResult:
            return SlashCommandResult(extras={"should_exit": True})

        @reg.register("trash", help_text="List deleted files")
        def _trash(args: list[str]) -> SlashCommandResult:
            from micron.tools.builtin import list_trash
            return SlashCommandResult(text=str(list_trash()))

        @reg.register("restore", help_text="Restore file from trash")
        def _restore(args: list[str]) -> SlashCommandResult:
            if not args:
                return SlashCommandResult(text="Usage: /restore <filename>")
            from micron.tools.builtin import restore_file
            return SlashCommandResult(text=str(restore_file(args[0])))

        @reg.register("purge", help_text="Empty trash permanently")
        def _purge(args: list[str]) -> SlashCommandResult:
            from micron.tools.builtin import purge_trash
            return SlashCommandResult(text=str(purge_trash()))

        @reg.register("undo", help_text="Restore from .bak backup")
        def _undo(args: list[str]) -> SlashCommandResult:
            if not args:
                return SlashCommandResult(text="Usage: /undo <filename>")
            from micron.tools.builtin import undo_file
            return SlashCommandResult(text=str(undo_file(args[0])))

        @reg.register("tree", help_text="Show directory tree")
        def _tree(args: list[str]) -> SlashCommandResult:
            return SlashCommandResult(text=self._tree(args))

    def _register_model_commands(self) -> None:
        """Register /models: list models and switch active backend."""
        reg = self.registry

        @reg.register("models", help_text="Open model picker / switch provider+model")
        def _models(args: list[str]) -> SlashCommandResult:
            return self._models(args)

    def _register_memory_commands(self) -> None:
        """Register /memory: list / delete individual memories."""
        reg = self.registry

        @reg.register("memory", help_text="Memory ops: delete <id>, list")
        def _memory(args: list[str]) -> SlashCommandResult:
            return self._memory(args)

    def handle(self, cmd: str) -> CommandResult:
        result = self.registry.dispatch(cmd)
        return CommandResult(
            text=result.text,
            clear_history=result.extras.get("clear_history", False),
            reload_sidebar=result.extras.get("reload_sidebar", False),
            loaded_skill=result.extras.get("loaded_skill"),
            resumed_history=result.extras.get("resumed_history"),
            should_exit=result.extras.get("should_exit", False),
            open_model_picker=result.extras.get("open_model_picker", False),
            model_entries=result.extras.get("model_entries", []),
        )

    def _help_text(self) -> str:
        return self.registry.help_text()

    def _memories(self) -> str:
        memories = self.agent.list_memories(10)
        if not memories:
            return "No memories stored."
        lines = [f"Recent memories ({len(memories)}):"]
        for m in memories:
            tags = " ".join(f"#{t}" for t in m.tags) if getattr(m, "tags", None) else ""
            lines.append(f"  [{m.id[:8]}] {m.text[:80]} {tags}")
        return "\n".join(lines)

    def _memory(self, args: list[str]) -> SlashCommandResult:
        """`/memory delete <id>` and `/memory list`."""
        if not args:
            return SlashCommandResult(text="Usage: /memory <delete|list> [args]")
        sub = args[0].lower()
        if sub == "delete":
            if len(args) < 2:
                return SlashCommandResult(text="Usage: /memory delete <id>")
            memory_id = args[1]
            ok = self.agent.memory.delete(memory_id)
            if ok:
                return SlashCommandResult(
                    text=f"Deleted memory {memory_id}.",
                    extras={"reload_sidebar": True},
                )
            return SlashCommandResult(text=f"Memory {memory_id} not found.")
        if sub == "list":
            return SlashCommandResult(
                text=self._memories(),
                extras={"reload_sidebar": True},
            )
        return SlashCommandResult(text=f"Unknown subcommand: {sub}. Usage: /memory <delete|list>")

    def _tools(self) -> str:
        tools = self.agent.tools.list()
        if not tools:
            return "No tools available."
        lines = [f"Available tools ({len(tools)}):"]
        for t in tools:
            write_tag = " [write]" if t.get("write", False) else ""
            lines.append(f"  {t['name']}: {t['description']}{write_tag}")
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

    # ── /models ──────────────────────────────────────────────────────────

    def _fetch_provider_models(self, prov_name: str, prov_cfg: dict) -> list[dict]:
        return self.catalog._source.fetch(prov_name, prov_cfg)

    def _all_model_entries(self) -> list[tuple[str, str, dict]]:
        from micron.config import load_config

        cfg = load_config()
        providers = cfg.get("providers", {}) if cfg else {}
        entries: list[tuple[str, str, dict]] = []
        for prov_name, prov_cfg in providers.items():
            live = self._fetch_provider_models(prov_name, prov_cfg)
            if live:
                entries.extend((prov_name, m["name"], m.get("meta", {})) for m in live)
                continue
            models = prov_cfg.get("models")
            if isinstance(models, list) and models:
                entries.extend((prov_name, m, {}) for m in models)
            elif prov_cfg.get("model"):
                entries.append((prov_name, prov_cfg["model"], {}))
        return entries

    def _format_model_meta_parts(self, meta: dict) -> tuple[str, str]:
        from micron.catalog import ModelEntry

        e = ModelEntry(provider="", name="", meta=meta)
        return e.price, e.rest

    def _format_model_meta(self, meta: dict) -> str:
        from micron.catalog import ModelEntry

        return ModelEntry(provider="", name="", meta=meta).detail

    def _format_model_list(self, entries: list[tuple[str, str, dict]]) -> str:
        from micron.catalog import ModelEntry

        # Support both tuple entries (legacy) and ModelEntry
        if entries and isinstance(entries[0], ModelEntry):
            return self.catalog.text(entries, active=(self.agent.provider, self.agent.model))
        # Convert tuple -> ModelEntry for catalog.text
        model_entries = [ModelEntry(provider=p, name=m, meta=meta) for p, m, meta in entries]
        return self.catalog.text(model_entries, active=(self.agent.provider, self.agent.model))

    def _models(self, args: list[str]) -> SlashCommandResult:
        entries = self._all_model_entries()

        if not args:
            self._last_models = entries
            # Convert to ModelEntry for catalog.text
            from micron.catalog import ModelEntry

            model_entries = [ModelEntry(provider=p, name=m, meta=meta) for p, m, meta in entries]
            return SlashCommandResult(
                text=self.catalog.text(model_entries, active=(self.agent.provider, self.agent.model)),
                extras={"open_model_picker": True, "model_entries": entries},
            )

        first = args[0]

        if first.isdigit():
            if not self._last_models:
                return SlashCommandResult(text="No model list yet — run /models first.")
            idx = int(first) - 1
            if idx < 0 or idx >= len(self._last_models):
                return SlashCommandResult(text=f"Index {first} out of range (1..{len(self._last_models)}).")
            prov, model, _meta = self._last_models[idx]
            return self._switch_model(prov, model)

        if len(args) == 1:
            provider = first
            provider_entries = [e for e in entries if e[0] == provider]
            if not provider_entries:
                if provider not in {p for (p, _m, _) in entries}:
                    providers = sorted({p for (p, _m, _) in entries})
                    return SlashCommandResult(text=f"Unknown provider: {provider}. Known: {', '.join(providers)}")
                return SlashCommandResult(text=f"No models for {provider}.")
            self._last_models = provider_entries
            from micron.catalog import ModelEntry

            model_entries = [ModelEntry(provider=p, name=m, meta=meta) for p, m, meta in provider_entries]
            return SlashCommandResult(
                text=self.catalog.text(model_entries, active=(self.agent.provider, self.agent.model)),
                extras={"open_model_picker": True, "model_entries": provider_entries},
            )

        provider, model = first, args[1]
        return self._switch_model(provider, model)

    def _switch_model(self, provider: str, model: str) -> SlashCommandResult:
        msg = self.catalog.switch(self.agent, provider, model)
        # Map catalog string to SlashCommandResult (status already encoded)
        if msg.startswith("Unknown provider") or msg.startswith("Failed"):
            return SlashCommandResult(text=msg)
        return SlashCommandResult(text=msg)

    def switch_model(self, provider: str, model: str) -> SlashCommandResult:
        """Public wrapper around _switch_model for the model picker."""
        return self._switch_model(provider, model)