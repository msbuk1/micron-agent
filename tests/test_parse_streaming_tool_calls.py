"""Tests for parse_streaming_tool_calls — the shared streaming tool-call parser."""
import json

import pytest

from micron.llm import LLMResponse, parse_streaming_tool_calls


# ---------------------------------------------------------------------------
# Helpers — lightweight stand-ins for SDK delta objects
# ---------------------------------------------------------------------------

class _Delta:
    """Mimics OpenAI SDK delta with attribute access."""
    def __init__(self, content=None, tool_calls=None, reasoning_content=None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content


class _ToolCall:
    def __init__(self, index=0, id=None, function=None):
        self.index = index
        self.id = id
        self.function = function


class _Function:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


# ---------------------------------------------------------------------------
# Basic text streaming
# ---------------------------------------------------------------------------

def test_text_only():
    deltas = [_Delta(content="Hello"), _Delta(content=" world")]
    result = list(parse_streaming_tool_calls(deltas))
    assert result == [
        LLMResponse(type="text", content="Hello"),
        LLMResponse(type="text", content=" world"),
        LLMResponse(type="done"),
    ]


def test_empty_stream():
    result = list(parse_streaming_tool_calls([]))
    assert result == [LLMResponse(type="done")]


def test_none_content_ignored():
    deltas = [_Delta(content=None), _Delta(content="ok")]
    result = list(parse_streaming_tool_calls(deltas))
    assert result == [
        LLMResponse(type="text", content="ok"),
        LLMResponse(type="done"),
    ]


# ---------------------------------------------------------------------------
# Reasoning
# ---------------------------------------------------------------------------

def test_reasoning_yielded():
    deltas = [_Delta(reasoning_content="thinking..."), _Delta(content="answer")]
    result = list(parse_streaming_tool_calls(deltas))
    assert result == [
        LLMResponse(type="reasoning", content="thinking..."),
        LLMResponse(type="text", content="answer"),
        LLMResponse(type="done"),
    ]


# ---------------------------------------------------------------------------
# Single tool call — streamed across chunks
# ---------------------------------------------------------------------------

def test_single_tool_call_streamed():
    deltas = [
        _Delta(tool_calls=[
            _ToolCall(index=0, id="call_0", function=_Function(name="read_file"))
        ]),
        _Delta(tool_calls=[
            _ToolCall(index=0, function=_Function(arguments='{"path": "'))
        ]),
        _Delta(tool_calls=[
            _ToolCall(index=0, function=_Function(arguments='foo.txt"}'))
        ]),
    ]
    result = list(parse_streaming_tool_calls(deltas))
    assert result == [
        LLMResponse(
            type="tool_call",
            tool_name="read_file",
            tool_args={"path": "foo.txt"},
            tool_call_id="call_0",
        ),
        LLMResponse(type="done"),
    ]


# ---------------------------------------------------------------------------
# Multiple tool calls — interleaved
# ---------------------------------------------------------------------------

def test_multiple_tool_calls_interleaved():
    deltas = [
        _Delta(tool_calls=[
            _ToolCall(index=0, id="c0", function=_Function(name="alpha")),
            _ToolCall(index=1, id="c1", function=_Function(name="beta")),
        ]),
        _Delta(tool_calls=[
            _ToolCall(index=0, function=_Function(arguments='{"a":1}')),
        ]),
        _Delta(tool_calls=[
            _ToolCall(index=1, function=_Function(arguments='{"b":2}')),
        ]),
    ]
    result = list(parse_streaming_tool_calls(deltas))
    tool_results = [r for r in result if r.type == "tool_call"]
    assert len(tool_results) == 2
    assert tool_results[0].tool_name == "alpha"
    assert tool_results[0].tool_args == {"a": 1}
    assert tool_results[1].tool_name == "beta"
    assert tool_results[1].tool_args == {"b": 2}


# ---------------------------------------------------------------------------
# Invalid JSON arguments — graceful fallback
# ---------------------------------------------------------------------------

def test_invalid_json_arguments():
    deltas = [
        _Delta(tool_calls=[
            _ToolCall(index=0, id="c0", function=_Function(name="fn", arguments="not json")),
        ]),
    ]
    result = list(parse_streaming_tool_calls(deltas))
    tool_call = [r for r in result if r.type == "tool_call"][0]
    assert tool_call.tool_args == {}


# ---------------------------------------------------------------------------
# Empty arguments → empty dict
# ---------------------------------------------------------------------------

def test_empty_arguments():
    deltas = [
        _Delta(tool_calls=[
            _ToolCall(index=0, id="c0", function=_Function(name="fn", arguments="")),
        ]),
    ]
    result = list(parse_streaming_tool_calls(deltas))
    tool_call = [r for r in result if r.type == "tool_call"][0]
    assert tool_call.tool_args == {}


def test_no_arguments_key():
    deltas = [
        _Delta(tool_calls=[
            _ToolCall(index=0, id="c0", function=_Function(name="fn")),
        ]),
    ]
    result = list(parse_streaming_tool_calls(deltas))
    tool_call = [r for r in result if r.type == "tool_call"][0]
    assert tool_call.tool_args == {}


# ---------------------------------------------------------------------------
# Dict-based deltas (Ollama style)
# ---------------------------------------------------------------------------

def test_dict_based_deltas():
    deltas = [
        {"content": "Hello", "tool_calls": None},
        {
            "content": None,
            "tool_calls": [
                {"index": 0, "id": "call_1", "function": {"name": "search", "arguments": '{"q":"test"}'}}
            ],
        },
    ]
    result = list(parse_streaming_tool_calls(deltas))
    assert result == [
        LLMResponse(type="text", content="Hello"),
        LLMResponse(
            type="tool_call",
            tool_name="search",
            tool_args={"q": "test"},
            tool_call_id="call_1",
        ),
        LLMResponse(type="done"),
    ]


def test_dict_multiple_tool_calls():
    deltas = [
        {
            "content": None,
            "tool_calls": [
                {"index": 0, "id": "c0", "function": {"name": "a", "arguments": '{"x":1}'}},
                {"index": 1, "id": "c1", "function": {"name": "b", "arguments": '{"y":2}'}},
            ],
        },
    ]
    result = list(parse_streaming_tool_calls(deltas))
    tool_results = [r for r in result if r.type == "tool_call"]
    assert len(tool_results) == 2
    assert tool_results[0].tool_name == "a"
    assert tool_results[1].tool_name == "b"


# ---------------------------------------------------------------------------
# Missing id → fallback to call_{idx}
# ---------------------------------------------------------------------------

def test_missing_id_fallback():
    deltas = [
        _Delta(tool_calls=[
            _ToolCall(index=0, function=_Function(name="fn")),
        ]),
    ]
    result = list(parse_streaming_tool_calls(deltas))
    tool_call = [r for r in result if r.type == "tool_call"][0]
    assert tool_call.tool_call_id == "call_0"


# ---------------------------------------------------------------------------
# Mixed text + tool calls
# ---------------------------------------------------------------------------

def test_mixed_text_and_tool_calls():
    deltas = [
        _Delta(content="Let me look that up."),
        _Delta(tool_calls=[
            _ToolCall(index=0, id="c0", function=_Function(name="read", arguments='{"path":"x"}'))
        ]),
        _Delta(content="Here's the result."),
    ]
    result = list(parse_streaming_tool_calls(deltas))
    # Text events come during iteration; tool calls are emitted after stream ends
    assert result == [
        LLMResponse(type="text", content="Let me look that up."),
        LLMResponse(type="text", content="Here's the result."),
        LLMResponse(type="tool_call", tool_name="read", tool_args={"path": "x"}, tool_call_id="c0"),
        LLMResponse(type="done"),
    ]


# ---------------------------------------------------------------------------
# Name accumulation across chunks (edge case — name split across deltas)
# ---------------------------------------------------------------------------

def test_name_accumulated():
    deltas = [
        _Delta(tool_calls=[
            _ToolCall(index=0, id="c0", function=_Function(name="read_"))
        ]),
        _Delta(tool_calls=[
            _ToolCall(index=0, function=_Function(name="file"))
        ]),
    ]
    result = list(parse_streaming_tool_calls(deltas))
    tool_call = [r for r in result if r.type == "tool_call"][0]
    assert tool_call.tool_name == "read_file"


# ---------------------------------------------------------------------------
# Only done — no content, no tool calls
# ---------------------------------------------------------------------------

def test_only_done():
    deltas = [_Delta()]
    result = list(parse_streaming_tool_calls(deltas))
    assert result == [LLMResponse(type="done")]


# ---------------------------------------------------------------------------
# Backward compatibility — existing LLMResponse fields preserved
# ---------------------------------------------------------------------------

def test_tool_call_response_fields():
    deltas = [
        _Delta(tool_calls=[
            _ToolCall(index=0, id="xyz", function=_Function(name="do_thing", arguments='{"k":"v"}'))
        ]),
    ]
    result = list(parse_streaming_tool_calls(deltas))
    tc = [r for r in result if r.type == "tool_call"][0]
    assert tc.tool_name == "do_thing"
    assert tc.tool_args == {"k": "v"}
    assert tc.tool_call_id == "xyz"
    assert tc.content == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
