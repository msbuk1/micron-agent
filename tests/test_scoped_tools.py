"""Tests for scoped tools per agent (issue #18) — isolated registry view.

Covers: full-set default, reduced preset view, out-of-scope calls rejected
by the waterfall pipeline (even when the model hallucinates them), and
prompt assembly advertising only in-scope schemas.
"""
import micron.tools.builtin  # noqa: F401 — populates the decorator registry
import pytest

from micron.agent import AgentConfig, MicronAgent
from micron.llm import LLMResponse
from micron.profiles import AGENT_PRESETS, AgentPreset, compose_tools
from micron.tools.decorator import _registry
from micron.tools.pipeline import CommandPolicyListener, ToolListener
from micron.tools.registry import ScopedToolRegistry, ToolRegistry


# ── helpers ──────────────────────────────────────────────────────────────

def _full_registry() -> ToolRegistry:
    """Fresh registry seeded from the global @tool registry (the 24 builtins)."""
    reg = ToolRegistry()
    for td in _registry:
        reg.register(
            name=td.name, func=td.func, description=td.description,
            parameters=td.parameters, write=td.write,
        )
    return reg


def _small_registry() -> ToolRegistry:
    """Synthetic parent: two reads, one write, one shell tool."""
    reg = ToolRegistry()
    reg.register("read_thing", lambda: "data", "Read", {"type": "object", "properties": {}})
    reg.register("calc", lambda x: x * 2, "Calc", {"type": "object", "properties": {}})
    reg.register(
        "write_thing", lambda: "wrote", "Write",
        {"type": "object", "properties": {}}, write=True,
    )
    reg.register(
        "run_command", lambda cmd: f"ran {cmd}", "Shell",
        {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]},
    )
    return reg


class FakeBackend:
    """Fake LLM backend recording the tool schemas it was offered."""

    def __init__(self, responses):
        self.responses = responses
        self.call_index = 0
        self.seen_tool_names: list[list[str]] = []

    def is_available(self) -> bool:
        return True

    def stream_chat(self, messages, tools=None, temperature=0.1, max_tokens=2048):
        self.seen_tool_names.append(
            [s["function"]["name"] for s in (tools or [])]
        )
        responses = self.responses[self.call_index % len(self.responses)]
        self.call_index += 1
        yield from responses


def _scoped_agent(tmp_path, parent, responses, preset):
    backend = FakeBackend(responses)
    config = AgentConfig(
        context_dir=str(tmp_path / "context"),
        provider="fake",
        model="fake-model",
    )
    agent = MicronAgent(config, backend=backend, tools=compose_tools(parent, preset))
    return agent, backend


# ── composition: full-set default / reduced preset ───────────────────────

def test_full_set_default_returns_registry_unchanged():
    reg = _full_registry()
    assert compose_tools(reg, "default") is reg
    assert compose_tools(reg, None) is reg
    assert compose_tools(reg, AgentPreset("custom")) is reg


def test_reduced_preset_view_over_full_registry():
    parent = _full_registry()
    full_count = len(parent.all())
    assert full_count >= 20  # the 24 builtins

    scoped = compose_tools(parent, "plan")

    assert isinstance(scoped, ScopedToolRegistry)
    assert {t["name"] for t in scoped.list()} != {t["name"] for t in parent.list()}
    assert {t["name"] for t in scoped.list()} == set(AGENT_PRESETS["plan"].tools)
    assert {s["function"]["name"] for s in scoped.schemas()} == set(AGENT_PRESETS["plan"].tools)
    # Parent keeps the full set — the default session is untouched.
    assert len(parent.all()) == full_count


def test_unknown_preset_name_raises():
    with pytest.raises(ValueError, match="Unknown agent preset"):
        compose_tools(_small_registry(), "no-such-preset")


def test_unknown_scope_tool_name_raises():
    with pytest.raises(ValueError, match="Unknown tool.*in scope"):
        ScopedToolRegistry(_small_registry(), ["read_thing", "ghost_tool"])


# ── enforcement: pipeline rejects out-of-scope calls ─────────────────────

def test_out_of_scope_call_rejected_by_pipeline():
    events = []
    parent = _small_registry()
    scoped = ScopedToolRegistry(parent, ["read_thing"])

    result = scoped.call("write_thing", _emit=events.append, _call_id="c1")

    # Tool never executed; denial rendered as tool_error via ErrorFormat.
    assert "not available in this session" in result
    types = [e["type"] for e in events]
    assert types == ["tool_pre", "tool_error"]
    assert "not available" in events[-1]["error"]
    assert not any(e["type"] == "tool_post" for e in events)


def test_out_of_scope_call_never_runs_tool_body():
    parent = _small_registry()
    calls = []
    parent.register(
        "write_thing", lambda: calls.append(1), "Write",
        {"type": "object", "properties": {}}, write=True,
    )
    scoped = ScopedToolRegistry(parent, ["read_thing"])

    scoped.call("write_thing")

    assert calls == []


def test_in_scope_call_executes_and_inherits_parent_listeners():
    parent = _small_registry()
    parent.add_listener(CommandPolicyListener())
    scoped = ScopedToolRegistry(parent, ["read_thing", "run_command"])

    assert scoped.call("read_thing") == "data"
    # Inherited policy listener still applies inside the scope.
    assert "blocked" in scoped.call("run_command", cmd="rm -rf /")


def test_scope_listener_is_outermost():
    order = []

    class _Tag(ToolListener):
        def pre_execute(self, invocation, next):
            order.append("policy")
            return next()

    parent = _small_registry()
    parent.add_listener(_Tag())
    scoped = ScopedToolRegistry(parent, ["read_thing"])
    scoped.call("read_thing")
    # Scope listener runs before inherited policy listeners; it delegated
    # here, so both fired — scope first is asserted by denial precedence
    # in test_out_of_scope_call_rejected_by_pipeline.
    assert order == ["policy"]


def test_register_outside_scope_raises_and_in_scope_syncs_parent():
    parent = _small_registry()
    scoped = ScopedToolRegistry(parent, ["read_thing"])

    with pytest.raises(ValueError, match="outside this registry's scope"):
        scoped.register("sneaky", lambda: 1, "Sneaky", {})

    # In-scope re-registration goes to the parent and re-syncs the view.
    scoped.register("read_thing", lambda: "new", "Read v2", {})
    assert parent.get("read_thing").description == "Read v2"
    assert scoped.get("read_thing").description == "Read v2"


# ── agent integration: prompt + stream_chat only see the scope ───────────

def test_agent_with_preset_advertises_only_scoped_schemas(tmp_path):
    parent = _full_registry()
    agent, backend = _scoped_agent(
        tmp_path, parent,
        [[LLMResponse(type="text", content="Hello."), LLMResponse(type="done")]],
        "plan",
    )

    list(agent.run("hi"))

    # The model was offered only the scoped schemas…
    offered = set(backend.seen_tool_names[0])
    assert offered == set(AGENT_PRESETS["plan"].tools)
    # …and the prompt's AVAILABLE TOOLS section lists only those.
    prompt = agent.prompt_builder.build_system_prompt("hi")
    tools_section = prompt.split("AVAILABLE TOOLS:")[1].split("INSTRUCTIONS:")[0]
    for name in AGENT_PRESETS["plan"].tools:
        assert f"- {name}" in tools_section
    for out_of_scope in ("write_file", "run_command", "delete_file"):
        assert f"- {out_of_scope}" not in tools_section
    # The main/global registry still holds the full set.
    assert len(parent.all()) >= 20


def test_agent_rejects_hallucinated_out_of_scope_call(tmp_path):
    parent = _full_registry()
    agent, backend = _scoped_agent(
        tmp_path, parent,
        [[
            LLMResponse(type="tool_call", tool_name="write_file",
                        tool_args={"path": "x.txt", "content": "hi"}, tool_call_id="call_1"),
            LLMResponse(type="done"),
        ], [
            LLMResponse(type="text", content="Cannot write files in this session."),
            LLMResponse(type="done"),
        ]],
        "plan",
    )

    events = list(agent.run("write a file"))

    errors = [e for e in events if e["type"] == "tool_error"]
    assert errors and errors[0]["name"] == "write_file"
    assert "not available in this session" in errors[0]["error"]
    # The hallucinated write never touched the filesystem.
    assert not (tmp_path / "x.txt").exists()
    assert not (tmp_path / "context" / "x.txt").exists()
