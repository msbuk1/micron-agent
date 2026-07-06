"""Tests for micron tool registry."""
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


if __name__ == "__main__":
    test_register_and_call()
    test_call_nonexistent_tool()
    test_is_write()
    test_schemas()
    test_write_tool_names()
    test_list_method()
    test_auto_detect_required()
    print("All tool registry tests passed!")