"""Tests for micron tool registry."""
from micron.tools.pipeline import CommandPolicyListener, ToolListener
from micron.tools.registry import ToolRegistry


def test_register_and_call():
    registry = ToolRegistry()
    
    def add(a: int, b: int) -> int:
        return a + b
    
    registry.register(
        name="add",
        func=add,
        description="Add two numbers",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"}
            },
            "required": ["a", "b"]
        }
    )
    
    result = registry.call("add", a=2, b=3)
    assert result == 5


def test_call_nonexistent_tool():
    registry = ToolRegistry()
    
    try:
        registry.call("nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Tool not found: nonexistent" in str(e)


def test_is_write():
    registry = ToolRegistry()
    
    def read_only():
        pass
    
    def write_tool():
        pass
    
    registry.register("read", read_only, "Read tool", {}, write=False)
    registry.register("write", write_tool, "Write tool", {}, write=True)
    
    assert registry.is_write("read") is False
    assert registry.is_write("write") is True
    assert registry.is_write("nonexistent") is False


def test_schemas():
    registry = ToolRegistry()
    
    def tool1():
        pass
    
    def tool2():
        pass
    
    registry.register("tool1", tool1, "Tool 1", {"type": "object", "properties": {}})
    registry.register("tool2", tool2, "Tool 2", {"type": "object", "properties": {}})
    
    schemas = registry.schemas()
    assert len(schemas) == 2
    
    names = {s["function"]["name"] for s in schemas}
    assert names == {"tool1", "tool2"}


def test_write_tool_names():
    registry = ToolRegistry()
    
    def read_only():
        pass
    
    def write_tool():
        pass
    
    registry.register("read", read_only, "Read tool", {}, write=False)
    registry.register("write", write_tool, "Write tool", {}, write=True)
    
    names = registry.write_tool_names()
    assert names == {"write"}


def test_list_method():
    registry = ToolRegistry()
    
    def tool1():
        pass
    
    registry.register("tool1", tool1, "Tool 1", {"type": "object", "properties": {"x": {"type": "string"}}}, write=True)
    
    tools = registry.list()
    assert len(tools) == 1
    assert tools[0]["name"] == "tool1"
    assert tools[0]["description"] == "Tool 1"
    assert tools[0]["write"] is True
    assert "x" in tools[0]["parameters"]["properties"]


def test_auto_detect_required():
    registry = ToolRegistry()
    
    def tool_with_required(a: str, b: int, c: str = "default"):
        pass
    
    registry.register(
        "tool_with_required",
        tool_with_required,
        "Tool with required params",
        {"type": "object", "properties": {}}
    )
    
    tool = registry.get("tool_with_required")
    assert "required" in tool.parameters
    assert set(tool.parameters["required"]) == {"a", "b"}


# Waterfall pipeline (pre/post-execute with next()/short-circuit)
# ---------------------------------------------------------------------------

class _Recorder(ToolListener):
    """Observe-only listener: records calls, always delegates."""

    def __init__(self):
        self.pre_seen = []
        self.post_seen = []

    def pre_execute(self, invocation, next):
        self.pre_seen.append((invocation.name, dict(invocation.args)))
        return next()

    def post_execute(self, invocation, result, next):
        self.post_seen.append((invocation.name, result))
        return next(result)


class _Annotator(ToolListener):
    """Annotate-and-delegate: wraps the delegated result."""

    def post_execute(self, invocation, result, next):
        return f"annotated({next(result)})"


class _Denier(ToolListener):
    """Owning listener: short-circuits pre-execute without next()."""

    def __init__(self, reason="denied by test"):
        self.reason = reason
        self.calls = []

    def pre_execute(self, invocation, next):
        self.calls.append(invocation.name)
        return self.reason


def _make_registry():
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, "Add", {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    })
    return registry


def test_observe_listener_delegates():
    events = []
    registry = _make_registry()
    recorder = _Recorder()
    registry.add_listener(recorder)

    result = registry.call("add", _emit=events.append, _call_id="c1", a=2, b=3)

    assert result == 5
    assert recorder.pre_seen == [("add", {"a": 2, "b": 3})]
    assert recorder.post_seen == [("add", 5)]
    types = [e["type"] for e in events]
    assert types == ["tool_pre", "tool_post"]
    assert events[0]["call_id"] == "c1"
    assert events[1]["result"] == 5


def test_annotate_and_delegate():
    registry = _make_registry()
    registry.add_listener(_Annotator())

    result = registry.call("add", a=2, b=3)
    assert result == "annotated(5)"


def test_short_circuit_deny():
    events = []
    registry = _make_registry()
    denier = _Denier()
    registry.add_listener(denier)

    result = registry.call("add", _emit=events.append, _call_id="c2", a=2, b=3)

    # Tool never executed; denial rendered as tool_error via ErrorFormat
    assert result == "denied by test"
    assert denier.calls == ["add"]
    types = [e["type"] for e in events]
    assert types == ["tool_pre", "tool_error"]
    assert "denied by test" in events[1]["error"]
    assert not any(e["type"] == "tool_post" for e in events)


def test_command_policy_listener_denies_blocked_command():
    events = []
    registry = _make_registry()
    registry.register("run_command", lambda cmd: f"ran {cmd}", "Run", {
        "type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"],
    })
    registry.add_listener(CommandPolicyListener())

    result = registry.call("run_command", _emit=events.append, cmd="rm -rf /")

    assert "blocked" in result
    assert events[-1]["type"] == "tool_error"
    assert not any(e["type"] == "tool_post" for e in events)


def test_command_policy_listener_allows_safe_command():
    registry = _make_registry()
    registry.register("run_command", lambda cmd: f"ran {cmd}", "Run", {
        "type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"],
    })
    registry.add_listener(CommandPolicyListener())

    assert registry.call("run_command", cmd="ls -la") == "ran ls -la"


def test_listener_chain_order():
    """First-added listener is outermost; both must delegate to execute."""
    order = []

    class _Tag(ToolListener):
        def __init__(self, tag):
            self.tag = tag

        def pre_execute(self, invocation, next):
            order.append(f"pre:{self.tag}")
            return next()

    registry = _make_registry()
    registry.add_listener(_Tag("outer"))
    registry.add_listener(_Tag("inner"))
    registry.call("add", a=1, b=1)
    assert order == ["pre:outer", "pre:inner"]


def test_tool_call_timeout():
    import time

    import pytest

    reg = ToolRegistry()

    def slow():
        time.sleep(5)
        return "done"

    reg.register("slow", slow, "Slow tool", {"type": "object", "properties": {}})
    with pytest.raises(TimeoutError, match="timed out"):
        reg.call("slow", timeout=0.2)


if __name__ == "__main__":
    test_register_and_call()
    test_call_nonexistent_tool()
    test_is_write()
    test_schemas()
    test_write_tool_names()
    test_list_method()
    test_auto_detect_required()
    test_observe_listener_delegates()
    test_annotate_and_delegate()
    test_short_circuit_deny()
    test_command_policy_listener_denies_blocked_command()
    test_command_policy_listener_allows_safe_command()
    test_listener_chain_order()
    print("All tool registry tests passed!")