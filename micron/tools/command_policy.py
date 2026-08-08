"""Command execution policy for run_command.

Centralises blocklist, flag scanning, injection guards, and resource limits
so that new rules are a one-line change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Allow:
    """Command is permitted."""


@dataclass(frozen=True)
class Deny:
    """Command is denied with a human-readable reason."""

    reason: str


@dataclass(frozen=True)
class Limit:
    """Command is permitted subject to resource limits.

    Any field that is ``None`` uses the process default (no override).
    """

    cpu: Optional[int] = None
    memory: Optional[int] = None
    procs: Optional[int] = None
    files: Optional[int] = None


# Union type alias for convenience.
Decision = Allow | Deny | Limit

# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------

BLOCKED_COMMANDS: set[str] = {
    "rm", "mkfs", "dd", "sudo", "chown", "chmod",
    "chsh", "useradd", "userdel", "passwd",
    "wget", "curl", "apt-get", "yum", "pacman",
}

SHELL_NAMES: frozenset[str] = frozenset({"bash", "sh", "zsh"})


class CommandPolicy:
    """Evaluates whether a parsed command (list of args) should be allowed.

    Usage::

        policy = CommandPolicy()
        decision = policy.evaluate(["rm", "-rf", "/"])
        # -> Deny(reason="Recursive delete is blocked")
    """

    def evaluate(self, args: list[str]) -> Decision:
        """Return an ``Allow``, ``Deny``, or ``Limit`` decision for *args*."""
        if not args:
            return Deny(reason="Empty command")

        unrestricted = os.getenv("MICRON_UNRESTRICTED", "").lower() in (
            "1", "true", "yes",
        )

        cmd_name = args[0].lower()

        # -- blocklist check (skipped in unrestricted mode) ---------------
        if not unrestricted:
            deny = self._check_blocklist(cmd_name, args)
            if deny is not None:
                return deny

        # -- flag / pattern scanning (skipped in unrestricted mode) -------
        if not unrestricted:
            deny = self._check_flags(args, cmd_name)
            if deny is not None:
                return deny

        # -- default: allow with standard limits -------------------------
        return Limit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_blocklist(self, cmd_name: str, args: list[str]) -> Deny | None:
        """Check *cmd_name* against the blocklist.

        Safe ``rm`` usage (no ``-r``/``-R`` flag) is allowed even when
        ``rm`` itself is on the blocklist.
        """
        if cmd_name not in BLOCKED_COMMANDS:
            return None

        # Special case: safe rm (no recursive flag)
        if cmd_name == "rm" and not any(
            a.startswith("-") and "r" in a.lower() for a in args[1:]
        ):
            return None

        return Deny(reason=f"Command '{cmd_name}' is blocked for security reasons")

    def _check_flags(self, args: list[str], cmd_name: str) -> Deny | None:
        """Scan every argument for dangerous flags / patterns."""
        for arg in args:
            arg_lower = arg.lower()

            # Recursive delete
            if cmd_name == "rm" and arg_lower.startswith("-") and "r" in arg_lower:
                return Deny(reason="rm -r/-rf is not allowed")

            # Pipe operator
            if arg == "|":
                return Deny(reason="shell pipes are not allowed")

            # Shell execution via path
            if arg.startswith("./") or arg.startswith("~/"):
                return Deny(reason="Executing scripts from path is blocked")

            # Command substitution
            if arg.startswith("$(") or arg.startswith("`"):
                return Deny(reason="Command substitution is blocked")

            # Redirect to block device
            if arg.startswith("/dev/sd") or arg.startswith("/dev/nvme"):
                return Deny(reason="Redirect to block device is blocked")

            # Shell names as arguments
            if arg_lower in SHELL_NAMES:
                return Deny(reason="cannot execute bash/sh/zsh")

        return None
