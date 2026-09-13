"""Issue #20 — session log as source of truth (deriveMessages + attempt vs message).

The append-only session log is the authority for model history: model
requests are projected from it, failed/cancelled streams persist as
log-only attempts, and a runtime check asserts model-visible content is
reconstructable from the log.
"""
import json
from pathlib import Path

import pytest

from micron.agent import AgentConfig, MicronAgent
from micron.llm import LLMResponse
from micron.sessions import FORMAT_VERSION, SessionLogger


class FakeBackend:
    """Records every message list it is asked to stream against."""

    def __init__(self, responses: list[list[LLMResponse]]):
        self.responses = responses
        self.call_index = 0
        self.messages_history: list[list[dict]] = []

    def is_available(self) -> bool:
        return True

    def stream_chat(self, messages, tools=None, temperature=0.1, max_tokens=2048):
        self.messages_history.append([dict(m) for m in messages])
        responses = self.responses[self.call_index % len(self.responses)]
        self.call_index += 1
        yield from responses


def make_agent(tmp_path: Path, responses, with_sessions=True):
    ctx = tmp_path / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    backend = FakeBackend(responses)
    config = AgentConfig(
        context_dir=str(ctx),
        provider="fake",
        model="fake-model",
        llm_kwargs={"backend": backend},
    )
    sessions = SessionLogger(tmp_path / "sessions")
    agent = MicronAgent(config, backend=backend, sessions=sessions if with_sessions else None)
    if with_sessions:
        sessions.start_session()
    return agent, backend, sessions


def test_header_carries_format_version(tmp_path):
    logger = SessionLogger(tmp_path / "sessions")
    sid = logger.start_session()
    assert logger.format_version(sid) == FORMAT_VERSION == 2
    header = json.loads((tmp_path / "sessions" / f"{sid}.jsonl").read_text().splitlines()[0])
    assert header["format_version"] == FORMAT_VERSION


def test_v1_session_migrates_forward_only_at_read(tmp_path):
    """Legacy v1 'turn' entries project as messages; the file is never rewritten."""
    d = tmp_path / "sessions"
    d.mkdir()
    lines = [
        json.dumps({"type": "session_start", "id": "old", "timestamp": "t"}),
        json.dumps({"type": "turn", "role": "user", "content": "hi"}),
        json.dumps({"type": "turn", "role": "assistant", "content": "hello"}),
    ]
    (d / "old.jsonl").write_text("\n".join(lines) + "\n")
    before = (d / "old.jsonl").read_text()

    logger = SessionLogger(d)
    assert logger.format_version("old") == 1
    msgs = logger.derive_messages("old")
    assert msgs == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    # Committed generation never rewritten in place.
    assert (d / "old.jsonl").read_text() == before


def test_attempts_never_enter_model_history(tmp_path):
    logger = SessionLogger(tmp_path / "sessions")
    sid = logger.start_session()
    logger.log_message("user", "what is 2+2?")
    logger.log_attempt("assistant", "I think the answer is... *stream dies*", reason="failed")
    logger.log_message("assistant", "4")

    derived = logger.derive_messages(sid)
    assert derived == [
        {"role": "user", "content": "what is 2+2?"},
        {"role": "assistant", "content": "4"},
    ]
    # Attempt is replayable / UI-visible in the full log.
    entries = logger.read_entries(sid)
    attempts = [e for e in entries if e["type"] == "attempt"]
    assert len(attempts) == 1
    assert attempts[0]["reason"] == "failed"
    assert "stream dies" in attempts[0]["content"]
    # Transcript projection excludes attempts too.
    assert all("stream dies" not in json.dumps(t) for t in logger.read_session(sid))
    assert sid


def test_agent_derives_history_from_log_not_side_channel(tmp_path):
    """Second request's history is projected from the log, ignoring the
    side-channel history list entirely."""
    agent, backend, sessions = make_agent(tmp_path, [
        [LLMResponse(type="text", content="First answer."), LLMResponse(type="done")],
        [LLMResponse(type="text", content="Second answer."), LLMResponse(type="done")],
    ])

    list(agent.run("question one"))
    # Single history path: the second request's history comes from the
    # log projection alone — there is no side-channel list to pollute it.
    list(agent.run("question two"))

    second_request = backend.messages_history[1]
    model_msgs = [m for m in second_request if m["role"] != "system"]
    assert model_msgs == [
        {"role": "user", "content": "question one"},
        {"role": "assistant", "content": "First answer."},
        {"role": "user", "content": "question two"},
    ]
    assert "STALE" not in json.dumps(second_request)


def test_failed_attempt_replayable_but_never_model_visible(tmp_path):
    """A stream that dies mid-way commits as an attempt; the next model
    request (resume/replay from the log) never sees its partial text."""
    agent, backend, sessions = make_agent(tmp_path, [
        # First call: streams partial text then errors.
        [LLMResponse(type="text", content="PARTIAL GARBAGE"), LLMResponse(type="error", content="boom")],
        # Retry: clean answer.
        [LLMResponse(type="text", content="Clean answer."), LLMResponse(type="done")],
    ])

    events = list(agent.run("tell me a fact"))
    assert any(e["type"] == "error" for e in events)

    # Attempt persisted, log-only.
    entries = sessions.read_entries(sessions.session_id)
    assert any(
        e["type"] == "attempt" and "PARTIAL GARBAGE" in e["content"] and e["reason"] == "failed"
        for e in entries
    )

    # Replay purely from the log: the model never sees the attempt.
    list(agent.run("try again"))
    second_request = json.dumps(backend.messages_history[1])
    assert "PARTIAL GARBAGE" not in second_request
    assert "tell me a fact" in second_request  # settled user message is there


def test_resume_and_transcript_read_same_projection(tmp_path):
    agent, backend, sessions = make_agent(tmp_path, [
        [LLMResponse(type="text", content="Answer A."), LLMResponse(type="done")],
    ])
    list(agent.run("hello"))
    sid = sessions.session_id

    # Resume path (get_session_context) and transcript (read_session) and
    # the agent's own projection (derive_messages) agree.
    resumed = sessions.get_session_context(sid)
    transcript = sessions.read_session(sid)
    derived = sessions.derive_messages(sid)
    assert resumed == derived
    assert [{"role": t["role"], "content": t["content"]} for t in transcript] == derived


def test_runtime_check_rejects_unlogged_model_visible_message(tmp_path):
    agent, backend, sessions = make_agent(tmp_path, [
        [LLMResponse(type="text", content="ok"), LLMResponse(type="done")],
    ])
    with pytest.raises(RuntimeError, match="not reconstructable from session log"):
        agent._verify_projection([
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "unlogged"},
        ])
    # System messages are exempt; logged content passes.
    sessions.log_message("user", "logged")
    agent._verify_projection([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "logged"},
    ])


def test_fork_seeds_child_from_projection_at_boundary(tmp_path):
    """Fork at a turn boundary: child derives the parent history prefix
    via the projection only; parent log untouched."""
    logger = SessionLogger(tmp_path / "sessions")
    parent = logger.start_session()
    logger.log_message("user", "q1")
    logger.log_message("assistant", "a1")
    logger.log_message("user", "q2")
    logger.log_message("assistant", "a2")
    before = (tmp_path / "sessions" / f"{parent}.jsonl").read_text()

    child = logger.fork_session(parent, max_messages=2)
    assert child != parent

    # Child header links to the parent.
    header = json.loads((tmp_path / "sessions" / f"{child}.jsonl").read_text().splitlines()[0])
    assert header["parent"] == parent
    assert header["format_version"] == FORMAT_VERSION

    # Child projection is exactly the last-2 prefix of the parent's.
    assert logger.derive_messages(child) == [
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    # Parent untouched.
    assert (tmp_path / "sessions" / f"{parent}.jsonl").read_text() == before
    assert logger.derive_messages(parent) == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]


def test_fork_excludes_attempts_but_parent_keeps_them(tmp_path):
    """Demo: a session with a failed attempt forks into a child that
    replays the conversation without the failure; the attempt stays
    replayable from the parent log."""
    logger = SessionLogger(tmp_path / "sessions")
    parent = logger.start_session()
    logger.log_message("user", "tell me a fact")
    logger.log_attempt("assistant", "PARTIAL GARBAGE", reason="failed")
    logger.log_message("assistant", "The sky is blue.")

    child = logger.fork_session(parent)

    child_derived = json.dumps(logger.derive_messages(child))
    assert "PARTIAL GARBAGE" not in child_derived
    assert logger.derive_messages(child) == [
        {"role": "user", "content": "tell me a fact"},
        {"role": "assistant", "content": "The sky is blue."},
    ]
    # Attempt still replayable from the parent's full log.
    attempts = [e for e in logger.read_entries(parent) if e["type"] == "attempt"]
    assert len(attempts) == 1 and attempts[0]["reason"] == "failed"
    # And absent from the child's full log too.
    assert not [e for e in logger.read_entries(child) if e["type"] == "attempt"]


def test_fork_carries_tool_exchange_messages(tmp_path):
    logger = SessionLogger(tmp_path / "sessions")
    parent = logger.start_session()
    logger.log_message("assistant", "", tool_calls=[{"id": "c1", "function": {"name": "echo", "arguments": "{}"}}])
    logger.log_message("tool", "echo: hi", tool_call_id="c1", name="echo")

    child = logger.fork_session(parent)
    assert logger.derive_messages(child) == logger.derive_messages(parent)


def test_tool_loop_messages_all_logged(tmp_path):
    """Assistant tool_calls + tool results commit as messages so the
    runtime check holds across a tool iteration."""
    agent, backend, sessions = make_agent(tmp_path, [
        [
            LLMResponse(type="tool_call", tool_name="echo", tool_args={"text": "hi"}, tool_call_id="c1"),
            LLMResponse(type="done"),
        ],
        [LLMResponse(type="text", content="done!"), LLMResponse(type="done")],
    ])
    from micron.tools.registry import ToolRegistry
    registry = ToolRegistry()
    registry.register(name="echo", func=lambda text: f"echo: {text}",
                      description="echo", parameters={"type": "object", "properties": {"text": {"type": "string"}}})
    agent.tools = registry

    events = list(agent.run("use echo"))
    assert not any(e["type"] == "error" for e in events)
    entries = sessions.read_entries(sessions.session_id)
    kinds = [(e["type"], e.get("role")) for e in entries]
    assert ("message", "assistant") in kinds
    assert ("message", "tool") in kinds
    # The second model request contains the tool exchange, all from the log.
    second = backend.messages_history[1]
    assert any(m["role"] == "tool" for m in second)
