"""Tests for the shared @tool decorator in micron/tools/decorator.py.

Covers signature->schema derivation, required params, types, defaults,
the write flag, and per-parameter description merging.
"""
import pytest

from micron.tools.decorator import tool, ToolDescriptor, _registry, clear


@pytest.fixture(autouse=True)
def clean_registry():
    """Isolate each test but preserve pre-existing registry contents.

    The shared ``_registry`` is a module-global that also holds built-in tools
    (registered when ``micron.tools.builtin`` is imported during the session).
    We snapshot it before and restore it after so this unit test does not
    destructively clear built-in registrations for other test modules.
    """
    saved = list(_registry)
    _registry.clear()
    yield
    # Restore prior contents; drop whatever THIS test appended.
    del _registry[:]
    _registry.extend(saved)


def test_schema_types_from_signature():
    @tool(name="greet", description="Greet someone")
    def greet(name: str, count: int = 1, ratio: float = 0.5, ok: bool = True) -> str:
        return f"hi {name} {count} {ratio} {ok}"

    assert len(_registry) == 1
    td = _registry[0]
    assert isinstance(td, ToolDescriptor)
    assert td.name == "greet"
    props = td.parameters["properties"]
    assert props["name"]["type"] == "string"
    assert props["count"]["type"] == "integer"
    assert props["ratio"]["type"] == "number"
    assert props["ok"]["type"] == "boolean"


def test_required_params_from_no_default():
    @tool(name="req", description="d")
    def req(a: str, b: int) -> str:  # neither has a default
        return a

    td = _registry[0]
    assert set(td.parameters["required"]) == {"a", "b"}


def test_defaults_not_required():
    @tool(name="opt", description="d")
    def opt(a: str, b: int = 5) -> str:
        return a

    td = _registry[0]
    assert "a" in td.parameters["required"]
    assert "b" not in td.parameters["required"]


def test_write_flag():
    @tool(name="reader", description="d")
    def reader(p: str) -> str:
        return p

    @tool(name="writer", description="d", write=True)
    def writer(p: str) -> str:
        return p

    by_name = {td.name: td for td in _registry}
    assert by_name["reader"].write is False
    assert by_name["writer"].write is True


def test_per_param_description_merged():
    @tool(
        name="search",
        description="Search things",
        query="Search query - use keywords not a question",
        max_results="Number of results (default 5)",
    )
    def search(query: str, max_results: int = 5) -> list:
        return []

    td = _registry[0]
    props = td.parameters["properties"]
    assert props["query"]["description"] == "Search query - use keywords not a question"
    assert props["max_results"]["description"] == "Number of results (default 5)"


def test_description_for_unknown_param_ignored():
    """passing a param description for a param that doesn't exist is a no-op."""
    @tool(name="t", description="d", nonexistent="ignored")
    def t(a: str) -> str:
        return a

    td = _registry[0]
    assert "nonexistent" not in td.parameters["properties"]


def test_decorator_returns_original_function():
    @tool(name="t", description="d")
    def t(a: str) -> str:
        return "works"

    # The decorator should return the original callable, not wrap/coerce it.
    assert t("x") == "works"
    assert _registry[0].func is t


def test_registry_can_hold_multiple_tools():
    @tool(name="a", description="d")
    def a(x: str) -> str:
        return x

    @tool(name="b", description="d")
    def b(x: str) -> str:
        return x

    assert len(_registry) == 2
    assert {t.name for t in _registry} == {"a", "b"}


def test_plugin_decorator_is_shared_descriptor():
    """Plugins must produce the SAME ToolDescriptor type as built-ins.

    This is the Slice 20 unification guard: `from micron.plugins import tool`
    resolves to the shared decorator, so a plugin-registered descriptor has
    type `micron.tools.decorator.ToolDescriptor` — not a local plugins copy.
    """
    from micron.plugins import tool as plugin_tool
    from micron.tools.decorator import ToolDescriptor as SharedTD

    # The re-exported decorator is literally the same object as the shared one.
    assert plugin_tool is tool

    @plugin_tool(name="p", description="plugin tool")
    def p(x: str) -> str:
        return x

    td = _registry[0]
    # Descriptor class identity (not just name) proves one shared type.
    assert type(td) is SharedTD
    assert td.__class__.__module__ == "micron.tools.decorator"
