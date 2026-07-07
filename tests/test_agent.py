"""Tests for micron agent loop and write-tool confirmation flow."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from micron.agent import MicronAgent, AgentConfig, ToolCall, create_agent
from micron.llm import LLMResponse


class FakeBackend:
    """Fake LLM backend for testing agent loops."""

    def __init__(self, responses: list[list[LLMResponse]]):
        self.responses = responses
        self.call_index = 0
        self.messages_history: list[list[dict]] = []

    def is_available(self) -> bool:
        return True

    def stream_chat(self, messages, tools=None, temperature=0.1, max_tokens=2048):
        self.messages_history.append([{"role": m["role"], **{k: m.get(k) for k in m if k != "role"}} for m in messages])
        responses = self.responses[self.call_index % len(self.responses)]
        self.call_index += 1
        yield from responses


def _write_tool_skill(tmpdir: Path):
    skill = tmpdir / "write_file.md"
    skill.write_text("""---
name: write_file
description: Write a file
write: true
module: micron.tools.builtin
parameters:
  type: object
  properties:
    path:
      type: string
    content:
      type: string
  required: [path, content]
---
""")


def _read_tool_skill(tmpdir: Path):
    skill = tmpdir / "read_file.md"
    skill.write_text("""---
name: read_file
description: Read a file
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    path:
      type: string
  required: [path]
---
""")


def make_agent(tmpdir: Path, responses: list[list[LLMResponse]], **kwargs):
    ctx = tmpdir / "context"
    skills_dir = ctx / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    _read_tool_skill(skills_dir)
    _write_tool_skill(skills_dir)

    backend = FakeBackend(responses)
    config = AgentConfig(
        context_dir=str(ctx),
        provider="fake",
        model="fake-model",
        llm_kwargs={"backend": backend, **kwargs},
    )
    agent = MicronAgent(config)
    agent.llm = backend
    return agent, backend


def test_read_tool_emits_proper_assistant_message():
    with tempfile.TemporaryDirectory() as tmpdir:
        agent, backend = make_agent(
            Path(tmpdir),
            [[
                LLMResponse(type="text", content=""),
                LLMResponse(type="tool_call", tool_name="read_file", tool_args={"path": "foo.txt"}, tool_call_id="call_1"),
                LLMResponse(type="done"),
            ], [
                LLMResponse(type="text", content="Done."),
                LLMResponse(type="done"),
            ]],
        )

        (Path(tmpdir) / "context" / "memory" / "foo.txt").parent.mkdir(parents=True, exist_ok=True)

        events = list(agent.run("read foo.txt"))
        text = "".join(e["content"] for e in events if e["type"] == "text")
        assert "Done." in text or any("Error" in str(e.get("error", "")) for e in events if e["type"] == "tool_error")

        # Tool result must be a role:tool message with correct tool_call_id
        # Check the last turn's messages (after tool execution)
        last_turn = backend.messages_history[-1]
        assistant_msg = next((m for m in last_turn if m["role"] == "assistant"), None)
        tool_msg = next((m for m in last_turn if m["role"] == "tool"), None)
        assert assistant_msg is not None
        assert tool_msg is not None
        assert "tool_calls" in assistant_msg
        assert assistant_msg["tool_calls"][0]["id"] == "call_1"
        assert tool_msg["tool_call_id"] == "call_1"


def test_write_tool_requires_confirmation():
    with tempfile.TemporaryDirectory() as tmpdir:
        agent, backend = make_agent(
            Path(tmpdir),
            [[
                LLMResponse(type="tool_call", tool_name="write_file", tool_args={"path": "x.txt", "content": "hi"}, tool_call_id="call_w1"),
                LLMResponse(type="done"),
            ]],
        )

        events = list(agent.run("write file"))
        assert any(e["type"] == "confirmation_required" for e in events)


def test_confirm_executes_write_call(tmpdir):
    tmp_path = Path(tmpdir)
    # Set workdir so write_file writes to the temp dir
    import os
    os.environ["MICRON_WORKDIR"] = str(tmp_path)
    try:
        agent, backend = make_agent(
            tmp_path,
            [
                [
                    LLMResponse(type="text", content="Wrote file."),
                    LLMResponse(type="done"),
                ]
            ],
        )

        pending = [ToolCall(name="write_file", args={"path": "out.txt", "content": "confirmed"}, call_id="call_w2", is_write=True)]
        events = list(agent.run("write it", confirm=True, pending_tool_calls=pending))
        assert any(e["type"] == "tool_result" and e["name"] == "write_file" for e in events)
        assert (tmp_path / "out.txt").read_text() == "confirmed"
    finally:
        os.environ.pop("MICRON_WORKDIR", None)


def test_loop_detection_stops_repeated_calls():
    with tempfile.TemporaryDirectory() as tmpdir:
        same_call = [
            LLMResponse(type="tool_call", tool_name="read_file", tool_args={"path": "loop.txt"}, tool_call_id="call_loop"),
            LLMResponse(type="done"),
        ]
        agent, backend = make_agent(Path(tmpdir), [same_call] * 10)
        events = list(agent.run("loop"))
        assert any("Loop detected" in str(e.get("message", "")) for e in events)


def test_text_tool_parsing_gated_by_provider():
    with tempfile.TemporaryDirectory() as tmpdir:
        text = '<function name="read_file">{"path": "foo.txt"}[PROMPT_INJECTION]'
        agent, _ = make_agent(
            Path(tmpdir),
            [[
                LLMResponse(type="text", content=text),
                LLMResponse(type="done"),
            ]],
        )
        # Fake provider is neither llamacpp nor ollama, text parsing disabled
        assert agent.use_text_tool_format is False
        events = list(agent.run("parse me"))
        assert not any(e["type"] == "tool_result" for e in events)


def test_local_provider_enables_text_parsing():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        text = '<function name="read_file">{"path": "foo.txt"}[PROMPT_INJECTION]'
        ctx = tmpdir / "context"
        (ctx / "skills").mkdir(parents=True)
        _read_tool_skill(ctx / "skills")
        _write_tool_skill(ctx / "skills")
        # Create target file so read_file succeeds
        os.environ["MICRON_WORKDIR"] = str(tmpdir)
        (tmpdir / "foo.txt").write_text("hello")

        backend = FakeBackend([[LLMResponse(type="text", content=text), LLMResponse(type="done")]])
        agent = create_agent(
            context_dir=str(ctx),
            provider="llamacpp",
            model="fake.gguf",
            llm_kwargs={"backend": backend},
        )
        agent.llm = backend
        assert agent.use_text_tool_format is True
        events = list(agent.run("parse me"))
        assert any(e["type"] == "tool_result" for e in events)

        # Reset workdir to project root after test
        os.environ.pop("MICRON_WORKDIR", None)


def test_history_compression_preserves_tool_pairs():
    history = []
    for i in range(15):
        history.append({"role": "user", "content": f"q{i}"})
        history.append({"role": "assistant", "content": f"a{i}"})

    with tempfile.TemporaryDirectory() as tmpdir:
        agent, _ = make_agent(Path(tmpdir), [])
        compressed = agent._compress_history(history, keep_recent=4)
        assert len(compressed) == 5  # summary + 4 recent
        assert compressed[0]["role"] == "user"
        assert "q0" in compressed[0]["content"]


def test_consecutive_failure_pivot():
    bad = [
        LLMResponse(type="text", content=""),
        LLMResponse(type="tool_call", tool_name="read_file", tool_args={"path": "missing"}, tool_call_id="f1"),
        LLMResponse(type="done"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        agent, backend = make_agent(Path(tmpdir), [bad] * 4)
        events = list(agent.run("fail"))
        # After 3 failures a pivot user message is injected
        flattened = [m for turn in backend.messages_history for m in turn]
        assert any("STOP and think differently" in str(m.get("content", "")) for m in flattened)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
