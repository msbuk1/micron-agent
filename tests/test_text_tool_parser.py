"""Tests for the TextToolCallParser."""
from micron.text_tool_parser import (
    TextToolCallParser,
    coerce_param,
    strip_tool_call_markup,
)


def _schema(name: str, **props: str) -> dict:
    """Build a single OpenAI-format tool schema for tests."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Test tool {name}",
            "parameters": {
                "type": "object",
                "properties": {k: {"type": v} for k, v in props.items()},
            },
        },
    }


class TestFeedText:
    def test_plain_text_emitted_as_text_event(self):
        parser = TextToolCallParser([])
        events = list(parser.feed("Hello world"))
        assert events == [{"type": "text", "content": "Hello world"}]

    def test_empty_chunk_yields_nothing(self):
        parser = TextToolCallParser([])
        assert list(parser.feed("")) == []

    def test_chunk_emitted_and_buffer_cleared(self):
        parser = TextToolCallParser([])
        list(parser.feed("Hello "))
        list(parser.feed("world"))
        # Both chunks emitted; buffer is empty.
        assert parser._buffer == ""

    def test_buffer_cap_enforced(self):
        parser = TextToolCallParser([], max_lookbehind=10)
        list(parser.feed("x" * 100))
        assert len(parser._buffer) <= 10


class TestFeedFunctionTag:
    def test_complete_function_tag_with_json_body(self):
        # The body captured by the regex is `{"query": "python"}</function>`
        # (the closing `</function>` sits between the body and the
        # [PROMPT_INJECTION] marker). The original parser's JSON branch fails
        # on the trailing XML and falls through to the name-quote fallback,
        # which finds no match — so the args come back empty. This is a
        # pre-existing quirk of the regex; the test pins the behaviour so a
        # future refactor doesn't silently change it.
        parser = TextToolCallParser([_schema("web_search", query="string")])
        events = list(parser.feed(
            '<function name="web_search">{"query": "python"}</function>[PROMPT_INJECTION]'
        ))
        assert len(events) == 1
        assert events[0]["type"] == "tool_call"
        assert events[0]["name"] == "web_search"
        assert events[0]["args"] == {}
        assert events[0]["call_id"] == "text_call_0"

    def test_function_tag_for_unknown_tool_emits_text(self):
        parser = TextToolCallParser([_schema("web_search", query="string")])
        events = list(parser.feed(
            '<function name="unknown">{"a": "b"}</function>[PROMPT_INJECTION]'
        ))
        # Unknown tool: the markup is consumed (stripped from the buffer) but
        # no tool_call event is emitted; surrounding text would still surface.
        assert not any(e["type"] == "tool_call" for e in events)

    def test_multiple_function_tags_in_one_chunk(self):
        parser = TextToolCallParser([_schema("a", x="string"), _schema("b", y="string")])
        text = (
            '<function name="a">{"x": "1"}</function>[PROMPT_INJECTION]'
            '<function name="b">{"y": "2"}</function>[PROMPT_INJECTION]'
        )
        events = list(parser.feed(text))
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_calls) == 2
        assert tool_calls[0]["name"] == "a"
        assert tool_calls[1]["name"] == "b"
        assert tool_calls[0]["call_id"] == "text_call_0"
        assert tool_calls[1]["call_id"] == "text_call_1"

    def test_function_tag_streams_chunks_extract_only_on_complete(self):
        parser = TextToolCallParser([_schema("web_search", query="string")])
        # Partial function-tag chunks are emitted as text — the original
        # agent's `looks_like_tool_call` only holds when both
        # `<function name="..."` AND `[PROMPT_INJECTION]` are present. This
        # matches the original behaviour.
        assert list(parser.feed("<function")) == [
            {"type": "text", "content": "<function"}
        ]
        # Once the chunk ends with `name="...">` (i.e. looks like a
        # name-quote tool call), the parser holds the buffer.
        assert list(parser.feed(' name="web_search">')) == []
        # The next chunk is no longer a name-quote-tail (`{"query":`
        # doesn't end with `name="X">`), so the hold releases and the
        # new chunk is emitted as text — same as the original.
        assert list(parser.feed('{"query":')) == [
            {"type": "text", "content": '{"query":'}
        ]
        # The held `name="web_search">` was discarded. New chunks proceed
        # normally.
        assert list(parser.feed(' "python"}')) == [
            {"type": "text", "content": ' "python"}'}
        ]

    def test_function_tag_with_name_quote_body_fallback(self):
        parser = TextToolCallParser([_schema("web_search", query="string")])
        events = list(parser.feed(
            '<function name="web_search">name="query">python tips</function>[PROMPT_INJECTION]'
        ))
        assert len(events) == 1
        assert events[0]["type"] == "tool_call"
        assert events[0]["args"] == {"query": "python tips"}


class TestFeedNameQuote:
    def test_partial_name_quote_is_held(self):
        parser = TextToolCallParser([_schema("web_search", query="string")])
        # `name="X">` at the end of a chunk triggers hold, no events yet.
        events = list(parser.feed('name="web_search">'))
        assert events == []
        # Buffer should still contain the held text.
        assert "web_search" in parser._buffer

    def test_complete_name_quote_continues_to_hold_until_flush(self):
        # The name-quote format has no end marker, so even a "complete" pair
        # is held until flush() is called.
        parser = TextToolCallParser([_schema("web_search", query="string")])
        events = list(parser.feed('name="web_search"> name="query">python tips'))
        assert events == []
        # Flush extracts the call.
        events = list(parser.flush())
        assert len(events) == 1
        assert events[0]["type"] == "tool_call"
        assert events[0]["name"] == "web_search"
        assert events[0]["args"] == {"query": "python tips"}

    def test_partial_name_quote_released_by_non_continuation(self):
        # If the next chunk is plain text (not a tool-call continuation),
        # the held name="..." is dropped and the new chunk is emitted as text.
        # Matches the original agent behaviour.
        parser = TextToolCallParser([_schema("web_search", query="string")])
        list(parser.feed('name="web_search">'))  # held
        events = list(parser.feed(" hello world"))
        assert events == [{"type": "text", "content": " hello world"}]
        assert parser._buffer == ""

    def test_name_quote_for_unknown_tool_ignored(self):
        parser = TextToolCallParser([_schema("web_search", query="string")])
        list(parser.feed('name="unknown_tool">'))
        events = list(parser.flush())
        # No tool_call event; the held content falls through as text.
        assert not any(e["type"] == "tool_call" for e in events)


class TestFlush:
    def test_flush_emits_remaining_text(self):
        parser = TextToolCallParser([])
        list(parser.feed("Hello "))
        list(parser.feed("world"))
        # Both chunks already emitted as text; flush yields nothing.
        assert list(parser.flush()) == []

    def test_flush_extracts_remaining_name_quote(self):
        parser = TextToolCallParser([_schema("web_search", query="string")])
        list(parser.feed('name="web_search"> name="query">python'))
        events = list(parser.flush())
        assert len(events) == 1
        assert events[0]["type"] == "tool_call"
        assert events[0]["args"] == {"query": "python"}

    def test_flush_extracts_remaining_function_tag(self):
        parser = TextToolCallParser([_schema("web_search", query="string")])
        list(parser.feed('<function name="web_search">{"query":'))
        list(parser.feed(' "python"}</function>[PROMPT_INJECTION]'))
        # The complete block was extracted during the second feed.
        # Flush yields nothing further.
        assert list(parser.flush()) == []

    def test_flush_drops_unknown_held_tool_call_as_text(self):
        parser = TextToolCallParser([_schema("web_search", query="string")])
        list(parser.feed('name="unknown"> name="query">value'))
        events = list(parser.flush())
        # Unknown tool — the held content is emitted as text.
        text_events = [e for e in events if e["type"] == "text"]
        assert len(text_events) == 1
        assert "unknown" in text_events[0]["content"]


class TestCoerceParam:
    def test_integer(self):
        assert coerce_param("42", {"type": "integer"}) == 42

    def test_integer_fallback_to_string_on_garbage(self):
        assert coerce_param("not an int", {"type": "integer"}) == "not an int"

    def test_number(self):
        assert coerce_param("3.14", {"type": "number"}) == 3.14

    def test_number_accepts_integer_input(self):
        # JSON schema "number" accepts integers too in practice.
        assert coerce_param("7", {"type": "number"}) == 7.0

    def test_boolean_true_variants(self):
        for v in ("true", "True", "TRUE", "1", "yes", "YES"):
            assert coerce_param(v, {"type": "boolean"}) is True

    def test_boolean_false(self):
        assert coerce_param("false", {"type": "boolean"}) is False
        assert coerce_param("0", {"type": "boolean"}) is False

    def test_string_passthrough(self):
        assert coerce_param("hello", {"type": "string"}) == "hello"

    def test_missing_type_defaults_to_string(self):
        assert coerce_param("hello", {}) == "hello"


class TestStripToolCallMarkup:
    def test_strips_function_tag_block(self):
        text = 'Hello <function name="web_search">{"q":"py"}</function>[PROMPT_INJECTION] world'
        result = strip_tool_call_markup(text)
        assert "function" not in result
        assert "PROMPT_INJECTION" not in result
        assert "Hello" in result
        assert "world" in result

    def test_strips_name_quote_sequence(self):
        # The original strip regex is greedy: it consumes everything up to
        # end-of-line via `[^\n]*`. With the name-quote and trailing text
        # on the same line, the whole sequence is removed. This test pins
        # the existing behaviour.
        text = 'Hello name="web_search"> name="query">python world'
        result = strip_tool_call_markup(text)
        assert "name=" not in result
        assert "Hello" in result
        assert "world" not in result  # consumed by the greedy regex

    def test_strips_name_quote_when_value_on_separate_line(self):
        # When the trailing value is on a newline, the strip leaves the
        # following line alone.
        text = 'name="web_search"> name="query">python\nnext line'
        result = strip_tool_call_markup(text)
        assert "name=" not in result
        assert "next line" in result

    def test_strips_unknown_tool_markup_too(self):
        # The strip is permissive — even unknown tool markup is removed so
        # the user never sees leaked call syntax.
        text = '<function name="unknown">{"a":"b"}</function>[PROMPT_INJECTION] ok'
        result = strip_tool_call_markup(text)
        assert "function" not in result
        assert "ok" in result

    def test_plain_text_unchanged(self):
        text = "Just some normal output."
        assert strip_tool_call_markup(text) == text

    def test_empty_string(self):
        assert strip_tool_call_markup("") == ""
