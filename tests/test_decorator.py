"""Tests for the shared @tool decorator in micron/tools/decorator.py.

Covers signature->schema derivation, required params, types, defaults,
the write flag, and per-parameter description merging.
"""
import pytest

from micron.tools.decorator import tool, ToolDescriptor, _registry, clear


@pytest.fixture(autouse=True)
def clean_registry():
    clear()
    yield
    clear()


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
