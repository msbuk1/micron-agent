"""Unified execution seam (issue #19) — fs + subprocess share one world."""
import os
from pathlib import Path

import pytest

from micron.execution import (
    FakeRemoteWorld,
    LocalWorld,
    get_world,
    reset_world,
    set_world,
)
from micron.tools.registry import ToolRegistry
from micron.tools.pipeline import CommandPolicyListener, SandboxListener
from micron.workspace import WorkspaceFS


@pytest.fixture(autouse=True)
def _restore_world():
    reset_world()
    yield
    reset_world()


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.setenv("MICRON_WORKDIR", str(tmp_path))
    return tmp_path


def _fake_remote(workdir):
    world = FakeRemoteWorld(WorkspaceFS(root=workdir))
    set_world(world)
    return world


# ── Local provider (default) ───────────────────────────────────────────

def test_default_provider_is_local(workdir):
    assert get_world().name == "local"
    assert isinstance(get_world(), LocalWorld)


def test_env_var_selects_provider(workdir, monkeypatch):
    monkeypatch.setenv("MICRON_EXECUTION_PROVIDER", "fake-remote")
    assert get_world().name == "fake-remote"


def test_local_file_tools_and_shell_work(workdir):
    from micron.tools.builtin import read_file, write_file, run_command

    assert "Success" in write_file("hello.txt", "ok")
    assert read_file("hello.txt") == "ok"
    out = run_command("echo hi")
    assert "hi" in out


def test_local_traversal_guard_holds(workdir):
    from micron.tools.builtin import read_file, write_file

    assert "escapes the working directory" in write_file("../evil.txt", "x")
    assert "escapes the working directory" in read_file("../evil.txt")


def test_local_blocklist_still_denies(workdir):
    from micron.tools.builtin import run_command

    out = run_command("rm -rf /")
    assert "Error" in out


# ── Fake-remote provider: all consumers move together ──────────────────

def test_fake_remote_file_tools_route_through_world(workdir):
    from micron.tools.builtin import read_file, write_file

    world = _fake_remote(workdir)
    write_file("a.txt", "alpha")
    assert read_file("a.txt") == "alpha"
    assert "write" in world.fs_calls
    assert "read" in world.fs_calls


def test_fake_remote_run_command_routes_through_world(workdir):
    from micron.tools.builtin import run_command

    world = _fake_remote(workdir)
    out = run_command("echo hi")
    assert "[fake-remote]" in out
    assert len(world.calls) == 1
    # Direct tool call: raw argv reaches the world; wrapping is the
    # pipeline listener's job (test_sandbox_wrap_applied_once_via_pipeline).
    assert world.calls[0]["cmd"] == ["echo", "hi"]
    assert world.wrap_count == 0


def test_sandbox_wrap_applied_once_via_pipeline(workdir):
    """The wrap happens in the pipeline listener, not per-tool."""
    registry = ToolRegistry()
    registry.add_listener(SandboxListener())
    world = _fake_remote(workdir)

    from micron.tools.decorator import _registry

    for td in _registry:
        if td.name == "run_command":
            registry.register(td.name, td.func, td.description, td.parameters, td.write)

    registry.call("run_command", cmd="echo piped")
    assert world.wrap_count == 1
    assert world.calls[0]["cmd"] == ["sandbox", "exec", "--", "echo", "piped"]


def test_local_world_never_wraps(workdir):
    registry = ToolRegistry()
    registry.add_listener(SandboxListener())
    world = get_world()
    assert world.name == "local"
    # Listener delegates without touching args on local worlds
    inv_args = {"cmd": "echo hi"}
    from micron.tools.pipeline import ToolInvocation

    seen = {}

    def execute():
        seen.update(inv_args)
        return "ran"

    registry.listeners.run_pre(ToolInvocation(name="run_command", args=inv_args), execute)
    assert seen == {"cmd": "echo hi"}


def test_fake_remote_blocklist_denies_before_spawn(workdir):
    """Policy still short-circuits remote execution."""
    registry = ToolRegistry()
    registry.add_listener(CommandPolicyListener())
    registry.add_listener(SandboxListener())
    world = _fake_remote(workdir)

    from micron.tools.decorator import _registry

    for td in _registry:
        if td.name == "run_command":
            registry.register(td.name, td.func, td.description, td.parameters, td.write)

    result = registry.call("run_command", cmd="rm -rf /")
    assert "Error" in str(result) or "blocked" in str(result).lower()
    assert world.calls == []  # never reached the remote world


def test_fake_remote_traversal_guard_holds(workdir):
    from micron.tools.builtin import write_file

    _fake_remote(workdir)
    assert "escapes the working directory" in write_file("../evil.txt", "x")


def test_swapping_provider_moves_all_consumers_together(workdir):
    """Flip local -> fake-remote -> local; every consumer follows."""
    from micron.tools.builtin import read_file, write_file, run_command

    write_file("x.txt", "one")
    assert read_file("x.txt") == "one"

    world = _fake_remote(workdir)
    write_file("y.txt", "two")
    assert read_file("y.txt") == "two"
    run_command("true")
    assert world.fs_calls and world.calls

    reset_world()
    assert get_world().name == "local"
    assert read_file("x.txt") == "one"
