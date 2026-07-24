"""Tests for the common event handler."""
import pytest
from micron.events import process_events, EventType, EventResult


def _make_events(*types_and_data):
    """Helper: yields event dicts from (type, data) pairs."""
    for event_type, data in types_and_data:
        chunk = {"type": event_type}
        if event_type == EventType.TEXT:
            chunk["content"] = data
        elif event_type == EventType.THINKING:
            chunk["content"] = data
        elif event_type == EventType.TOOL_START:
            chunk["name"] = data[0]
            chunk["call_id"] = data[1]
        elif event_type == EventType.TOOL_RESULT:
            chunk["name"] = data[0]
            chunk["summary"] = data[1]
        elif event_type == EventType.TOOL_ERROR:
            chunk["name"] = data[0]
            chunk["error"] = data[1]
        elif event_type == EventType.ERROR:
            chunk["message"] = data
        elif event_type == EventType.CONFIRMATION_REQUIRED:
            chunk["pending_writes"] = data
        # DONE has no data
        yield chunk


class TestProcessEvents:
    """Tests for process_events routing."""

    def test_text_accumulation(self):
        """Test that text chunks are accumulated."""
        gen = _make_events(
            (EventType.TEXT, "hello "),
            (EventType.TEXT, "world"),
            (EventType.DONE, None),
        )
        result = process_events(gen)
        assert result.text == "hello world"

    def test_thinking_callback(self):
        """Test that thinking events invoke on_thinking."""
        thinking_texts = []
        gen = _make_events(
            (EventType.THINKING, "let me think"),
            (EventType.TEXT, "answer"),
            (EventType.DONE, None),
        )
        process_events(gen, on_thinking=lambda t: thinking_texts.append(t))
        assert thinking_texts == ["let me think"]

    def test_tool_start_callback(self):
        """Test that tool_start events invoke on_tool_start."""
        tools = []
        gen = _make_events(
            (EventType.TOOL_START, ("read_file", "call_0")),
            (EventType.DONE, None),
        )
        process_events(gen, on_tool_start=lambda name, cid: tools.append(name))
        assert tools == ["read_file"]

    def test_tool_result_callback(self):
        """Test that tool_result events invoke on_tool_result."""
        results = []
        gen = _make_events(
            (EventType.TOOL_RESULT, ("write_file", "Success")),
            (EventType.DONE, None),
        )
        process_events(gen, on_tool_result=lambda name, s: results.append((name, s)))
        assert results == [("write_file", "Success")]

    def test_tool_error_callback(self):
        """Test that tool_error events invoke on_tool_error."""
        errors = []
        gen = _make_events(
            (EventType.TOOL_ERROR, ("run_command", "Permission denied")),
            (EventType.DONE, None),
        )
        process_events(gen, on_tool_error=lambda name, e: errors.append(e))
        assert errors == ["Permission denied"]

    def test_error_callback(self):
        """Test that error events invoke on_error."""
        errors = []
        gen = _make_events(
            (EventType.ERROR, "something broke"),
            (EventType.DONE, None),
        )
        process_events(gen, on_error=lambda m: errors.append(m))
        assert errors == ["something broke"]

    def test_confirmation_required(self):
        """Test that confirmation_required sets pending_writes."""
        writes = [{"tool_name": "write_file", "args": {"path": "x.txt"}}]
        gen = _make_events(
            (EventType.TEXT, "I need to write"),
            (EventType.CONFIRMATION_REQUIRED, writes),
        )
        result = process_events(gen)
        assert result.pending_writes == writes
        assert result.text == "I need to write"

    def test_done_stops_iteration(self):
        """Test that DONE stops the generator early."""
        def lazy_gen():
            yield {"type": EventType.TEXT, "content": "before"}
            yield {"type": EventType.DONE}
            yield {"type": EventType.TEXT, "content": "after"}  # should not be reached

        result = process_events(lazy_gen())
        assert result.text == "before"

    def test_no_callbacks_still_accumulates(self):
        """Test that text is accumulated even without callbacks."""
        gen = _make_events(
            (EventType.TEXT, "a"),
            (EventType.THINKING, "b"),
            (EventType.TOOL_START, ("x", "c")),
            (EventType.TEXT, "d"),
            (EventType.DONE, None),
        )
        result = process_events(gen)
        assert result.text == "ad"

    def test_full_agent_flow(self):
        """Test a realistic agent event sequence."""
        events = [
            {"type": "thinking", "content": "analyzing..."},
            {"type": "text", "content": "Let me "},
            {"type": "text", "content": "check that."},
            {"type": "tool_start", "name": "read_file", "call_id": "c1"},
            {"type": "tool_result", "name": "read_file", "summary": "file contents"},
            {"type": "text", "content": "\nThe file says hello."},
            {"type": "done"},
        ]

        thinking = []
        tools_started = []
        tools_done = []

        result = process_events(
            iter(events),
            on_thinking=lambda t: thinking.append(t),
            on_tool_start=lambda n, c: tools_started.append(n),
            on_tool_result=lambda n, s: tools_done.append(n),
        )

        assert result.text == "Let me check that.\nThe file says hello."
        assert thinking == ["analyzing..."]
        assert tools_started == ["read_file"]
        assert tools_done == ["read_file"]
