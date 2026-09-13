"""Unified execution seam — one swappable "world" for fs + subprocess.

Three roles, one module:

- **Service definition** — :class:`ExecutionWorld`: the operations any
  execution provider must offer (a WorkspaceFS-compatible ``fs`` plus
  ``run`` for shell execution and ``sandbox_wrap`` for confinement).
- **Provider** — :class:`LocalWorld` (WorkspaceFS + subprocess with
  resource limits) and :class:`FakeRemoteWorld` (records calls, wraps
  argv). Selected via ``MICRON_EXECUTION_PROVIDER`` env var or the
  ``execution.provider`` key in micron.yaml (default ``local``).
- **Consumer access** — :func:`get_world` / :func:`set_world` /
  :func:`reset_world`. File tools resolve ``world.fs``; ``run_command``
  resolves ``world.run``. Swapping the provider moves every consumer
  together — no per-tool forks.

Sandbox confinement is applied once, before spawn, by the
:class:`~micron.tools.pipeline.SandboxListener` in the tool pipeline —
not per-tool.
"""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "CommandResult",
    "ExecutionWorld",
    "LocalWorld",
    "FakeRemoteWorld",
    "RecordingFS",
    "get_world",
    "set_world",
    "reset_world",
]


@dataclass
class CommandResult:
    """Outcome of one shell execution."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class ExecutionWorld(ABC):
    """The execution world every consumer resolves through."""

    #: WorkspaceFS-compatible filesystem view (read/write/edit/list/...).
    fs: Any

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (``local``, ``fake-remote``, ...)."""

    @abstractmethod
    def run(
        self,
        cmd: str | list[str],
        *,
        shell: bool,
        cwd: Path,
        timeout: int,
        limits: Any = None,
    ) -> CommandResult:
        """Execute ``cmd`` (argv list, or string when ``shell=True``)."""

    def sandbox_wrap(self, cmd: str) -> str:
        """Wrap a command for sandbox confinement.

        Local worlds run commands as-is; remote providers may prefix a
        sandbox invocation. Applied once by the pipeline listener.
        """
        return cmd


class LocalWorld(ExecutionWorld):
    """Default provider: WorkspaceFS + subprocess with resource limits."""

    def __init__(self, workspace: Any):
        self.fs = workspace

    @property
    def name(self) -> str:
        return "local"

    def run(self, cmd, *, shell, cwd, timeout, limits=None):
        preexec = lambda: _set_command_resource_limits(limits)  # noqa: E731
        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
            preexec_fn=preexec,
        )
        return CommandResult(
            stdout=result.stdout, stderr=result.stderr, returncode=result.returncode
        )


class RecordingFS:
    """WorkspaceFS facade that records which ops flow through the world."""

    def __init__(self, workspace: Any, log: list):
        self._ws = workspace
        self.log = log

    def _record(self, op):
        self.log.append(op)
        return self._ws

    def read(self, path, **kw):
        self._record("read")
        return self._ws.read(path, **kw)

    def write(self, path, content, **kw):
        self._record("write")
        return self._ws.write(path, content, **kw)

    def edit(self, path, old, new, **kw):
        self._record("edit")
        return self._ws.edit(path, old, new, **kw)

    def patch(self, path, patches, **kw):
        self._record("patch")
        return self._ws.patch(path, patches, **kw)

    def delete(self, path):
        self._record("delete")
        return self._ws.delete(path)

    def list(self, path="."):
        self._record("list")
        return self._ws.list(path)

    def tree(self, path=".", **kw):
        self._record("tree")
        return self._ws.tree(path, **kw)

    def exists(self, path):
        return self._ws.exists(path)

    def undo(self, path):
        self._record("undo")
        return self._ws.undo(path)

    def restore(self, name, **kw):
        self._record("restore")
        return self._ws.restore(name, **kw)

    def trash(self):
        return self._ws.trash()

    def purge_trash(self):
        self._record("purge_trash")
        return self._ws.purge_trash()

    @property
    def root(self):
        return self._ws.root


class FakeRemoteWorld(ExecutionWorld):
    """Test/demo provider: records every consumer call, never spawns.

    ``run`` records the (already sandbox-wrapped) argv and returns a
    canned result; ``sandbox_wrap`` prefixes a fake sandbox invocation
    and counts how many times wrapping was applied (must be once).
    """

    def __init__(self, workspace: Any):
        self.fs_calls: list[str] = []
        self.fs = RecordingFS(workspace, self.fs_calls)
        self.calls: list[dict] = []
        self.wrap_count = 0

    @property
    def name(self) -> str:
        return "fake-remote"

    def sandbox_wrap(self, cmd: str) -> str:
        self.wrap_count += 1
        return f"sandbox exec -- {cmd}"

    def run(self, cmd, *, shell, cwd, timeout, limits=None):
        self.calls.append(
            {"cmd": cmd, "shell": shell, "cwd": str(cwd), "timeout": timeout}
        )
        return CommandResult(stdout=f"[fake-remote] {cmd}", returncode=0)


# ── Provider resolution ────────────────────────────────────────────────

_world = None
_world_env_snapshot = None
_world_overridden = False


def _provider_name() -> str:
    import os

    env = os.getenv("MICRON_EXECUTION_PROVIDER")
    if env:
        return env
    try:
        from micron.config import Config

        exec_cfg = Config().get("execution") or {}
        return exec_cfg.get("provider", "local")
    except Exception:
        return "local"


def _build_world(provider: str) -> ExecutionWorld:
    from micron.workspace import WorkspaceFS
    from micron.tools.builtin import _get_workdir

    workspace = WorkspaceFS(root=_get_workdir())
    if provider == "fake-remote":
        return FakeRemoteWorld(workspace)
    return LocalWorld(workspace)


def get_world() -> ExecutionWorld:
    """Return the process-wide execution world (built lazily, cached)."""
    global _world, _world_env_snapshot
    if _world is not None and _world_overridden:
        return _world
    provider = _provider_name()
    workdir = str(_workdir_from_provider())
    key = (provider, workdir)
    if _world is None or _world_env_snapshot != key:
        _world = _build_world(provider)
        _world_env_snapshot = key
    return _world


def _workdir_from_provider() -> Path:
    from micron.tools.builtin import _get_workdir

    return _get_workdir()


def set_world(world: ExecutionWorld) -> None:
    """Override the provider (tests / demo flips)."""
    global _world, _world_env_snapshot, _world_overridden
    _world = world
    _world_env_snapshot = world.name
    _world_overridden = True


def reset_world() -> None:
    """Drop the cached world so the next ``get_world`` re-resolves config."""
    global _world, _world_env_snapshot, _world_overridden
    _world = None
    _world_env_snapshot = None
    _world_overridden = False


# ── Resource limits (moved from tools/builtin.py; same behaviour) ──────


def _set_command_resource_limits(decision=None):
    """Set resource limits for command execution.

    *decision* may be a :class:`~micron.tools.command_policy.Limit` instance
    whose non-``None`` fields override the env-var defaults.

    Called via ``preexec_fn`` — runs in the child after fork, before exec.
    """
    import os

    try:
        import resource
    except ImportError:
        return

    from micron.tools.command_policy import Limit

    limit: Limit | None = decision if isinstance(decision, Limit) else None

    def _val(override, env_key, default):
        if override is not None:
            return override
        return int(os.getenv(env_key, default))

    try:
        if hasattr(resource, "RLIMIT_CPU"):
            v = _val(limit.cpu if limit else None, "MICRON_CMD_MAX_CPU", "60")
            resource.setrlimit(resource.RLIMIT_CPU, (v, v))
    except (ValueError, OSError):
        pass

    try:
        if hasattr(resource, "RLIMIT_AS"):
            mb = _val(limit.memory if limit else None, "MICRON_CMD_MAX_MEMORY_MB", "512")
            b = mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
    except (ValueError, OSError):
        pass

    try:
        if hasattr(resource, "RLIMIT_NPROC"):
            v = _val(limit.procs if limit else None, "MICRON_CMD_MAX_PROCESSES", "50")
            resource.setrlimit(resource.RLIMIT_NPROC, (v, v))
    except (ValueError, OSError):
        pass

    try:
        if hasattr(resource, "RLIMIT_NOFILE"):
            v = _val(limit.files if limit else None, "MICRON_CMD_MAX_FILES", "100")
            resource.setrlimit(resource.RLIMIT_NOFILE, (v, v))
    except (ValueError, OSError):
        pass
