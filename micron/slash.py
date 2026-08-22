"""Transport-agnostic slash command registry.

Owns the dispatch logic for `/command` queries used by the TUI and CLI.
A handler takes a list of argument strings and returns a
:class:`SlashCommandResult`. No Textual, no I/O — anything UI-specific
(clear-history flags, sidebar reloads, screen pushes) is expressed as a
key in the result's ``extras`` dict, and the caller translates that
into whatever transport-specific event it needs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SlashCommand:
    """One registered slash command."""
    name: str
    handler: Callable[[list[str]], "SlashCommandResult"]
    help_text: str = ""
    aliases: tuple[str, ...] = ()


@dataclass
class SlashCommandResult:
    """Return value from a slash command handler."""
    text: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[list[str]], SlashCommandResult]


class SlashCommandRegistry:
    """Maps `/name` to a handler. Stateless apart from the registry itself.

    Multiple commands can register the same handler under different
    names; aliases share the same :class:`SlashCommand` object.

    Usage::

        reg = SlashCommandRegistry()
        @reg.register("help", help_text="Show help")
        def _help(args):
            return SlashCommandResult(text=reg.help_text())
        reg.dispatch("/help")
    """

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(
        self,
        name: str,
        help_text: str = "",
        aliases: tuple[str, ...] | list[str] = (),
    ) -> Callable[[Handler], Handler]:
        """Decorator factory: ``@reg.register("name", help="…")``.

        Returns a decorator that registers ``func`` as the handler.
        """
        def decorator(func: Handler) -> Handler:
            cmd = SlashCommand(
                name=name,
                handler=func,
                help_text=help_text,
                aliases=tuple(aliases),
            )
            self._commands[name] = cmd
            for alias in aliases:
                self._commands[alias] = cmd
            return func
        return decorator

    def add(
        self,
        name: str,
        handler: Handler,
        help_text: str = "",
        aliases: tuple[str, ...] | list[str] = (),
    ) -> SlashCommand:
        """Imperative form of :meth:`register` — returns the :class:`SlashCommand`."""
        cmd = SlashCommand(
            name=name,
            handler=handler,
            help_text=help_text,
            aliases=tuple(aliases),
        )
        self._commands[name] = cmd
        for alias in aliases:
            self._commands[alias] = cmd
        return cmd

    def get(self, name: str) -> SlashCommand | None:
        """Look up a command by primary name or alias."""
        return self._commands.get(name)

    def all(self) -> list[SlashCommand]:
        """List all unique commands (deduped by identity, aliases share)."""
        seen: set[int] = set()
        out: list[SlashCommand] = []
        for cmd in self._commands.values():
            if id(cmd) in seen:
                continue
            seen.add(id(cmd))
            out.append(cmd)
        return out

    def suggest(self, prefix: str) -> list[SlashCommand]:
        """Return commands matching prefix (without leading slash)."""
        p = prefix.lstrip("/").lower()
        if not p:
            return self.all()
        return [c for c in self.all() if c.name.startswith(p) or any(a.startswith(p) for a in c.aliases)]

    def dispatch(self, query: str) -> SlashCommandResult:
        """Parse ``/name [args...]`` and invoke the matching handler.

        Returns a :class:`SlashCommandResult` on both success and
        unknown-command paths. The text of the result is safe to show
        to the user.
        """
        query = query.strip()
        if not query:
            return SlashCommandResult(text="Empty command.")
        if not query.startswith("/"):
            return SlashCommandResult(text=f"Commands must start with /. Got: {query!r}")
        parts = query.split()
        name = parts[0][1:].lower()
        args = parts[1:]
        if not name:
            return SlashCommandResult(text=self.help_text())
        cmd = self._commands.get(name)
        if cmd is None:
            # Suggest close matches for unknown prefix
            sug = self.suggest(name)
            if sug:
                lines = [f"Unknown command: /{name}. Did you mean:"]
                for c in sug[:5]:
                    lines.append(f"  /{c.name:<12} {c.help_text}")
                lines.append("Try /help for all commands")
                return SlashCommandResult(text="\n".join(lines))
            return SlashCommandResult(text=f"Unknown command: /{name}. Try /help")
        return cmd.handler(args) or SlashCommandResult()

    def help_text(self) -> str:
        """Auto-generate a help block from registered commands."""
        lines = ["Commands:"]
        for cmd in self.all():
            alias_str = f", /{', /'.join(cmd.aliases)}" if cmd.aliases else ""
            name_col = f"/{cmd.name}{alias_str}"
            lines.append(f"  {name_col:<22} {cmd.help_text}")
        return "\n".join(lines)