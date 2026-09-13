"""Tests for turn/step lifecycle, inbox inject, and hooks (issue #17)."""
import tempfile
from pathlib import Path

from micron.agent import MicronAgent, AgentConfig
from micron.llm import LLMResponse
from micron.turns import TurnHooks


class FakeBackend:
    def __init__(self, responses: list[list[LLMResponse]]):
        self.responses = responses
        self.call_index = 0
        self.messages_history: list[list[dict]] = []

    def is_available(self) -> bool:
        return True

    def stream_chat(self, messages, tools=None, temperature=0.1, max_tokens=2048):
        self.messages_history.append(list(messages))
        responses = self.responses[self.call_index % len(self.responses)]
        self.call_index += 1
        yield from responses


def make_agent(tmpdir: Path, responses, hooks=None):
    ctx = tmpdir / "context"
    (ctx / "skills").mkdir(parents=True, exist_ok=True)
    backend = FakeBackend(responses)
    config = AgentConfig(
        context_dir=str(ctx), provider="fake", model="fake-model",
        llm_kwargs={"backend": backend},
    )
    agent = MicronAgent(config, hooks=hooks)
    agent.llm = backend
    return agent, backend


def _tool_then_done():
    return [
        [
            LLMResponse(type="tool_call", tool_name="list_files", tool_args={"path": "."}, tool_call_id="c1"),
            LLMResponse(type="done"),
        ],
        [
            LLMResponse(type="text", content="All done."),
            LLMResponse(type="done"),
        ],
    ]


def test_turn_lifecycle_events_wrap_steps(tmp_path):
    agent, backend = make_agent(tmp_path, _tool_then_done())
    events = list(agent.run("do it"))
    types = [e["type"] for e in events]
    assert types[0] == "turn_start"
    assert types[-1] == "turn_end"
    # two steps: tool step + final text step
    assert types.count("step_start") == 2
    assert types.count("step_end") == 2
    # steps are nested inside the turn
    assert types.index("step_start") > types.index("turn_start")
    assert types.index("turn_end") > types.index("step_end")
    assert events[0]["turn_id"] == events[-1]["turn_id"]


def test_inject_before_run_lands_in_first_request(tmp_path):
    agent, backend = make_agent(tmp_path, _tool_then_done())
    agent.inject("remember: the vault code is 1234")
    list(agent.run("do it"))
    first_request = backend.messages_history[0]
    injected = [m for m in first_request if m["role"] == "user" and "vault code" in m.get("content", "")]
    assert len(injected) == 1
    # wake message comes before the injected context
    assert first_request.index({"role": "user", "content": "do it"}) < first_request.index(injected[0])


def test_inject_mid_turn_lands_next_request_never_mid_stream(tmp_path):
    agent, backend = make_agent(tmp_path, _tool_then_done())
    gen = agent.run("do it")
    seen = []
    for ev in gen:
        seen.append(ev)
        if ev["type"] == "tool_result":
            agent.inject("mid-turn context")
    types = [e["type"] for e in seen]
    assert "mid-turn context" not in "".join(
        e.get("content", "") for e in seen if e["type"] == "text"
    )
    # second request (the continuation) carries the injected context
    second = backend.messages_history[1]
    assert any(m["role"] == "user" and "mid-turn context" in m.get("content", "") for m in second)


def test_pre_step_hook_rewrites_input(tmp_path):
    class Rewrite(TurnHooks):
        def pre_step(self, message):
            return message + " (rewritten)"

    agent, backend = make_agent(tmp_path, _tool_then_done(), hooks=Rewrite())
    list(agent.run("do it"))
    first_user = [m for m in backend.messages_history[0] if m["role"] == "user"][-1]
    assert first_user["content"] == "do it (rewritten)"


def test_pre_step_hook_reject_closes_turn_with_no_step(tmp_path):
    class Reject(TurnHooks):
        def pre_step(self, message):
            return None

    agent, backend = make_agent(tmp_path, _tool_then_done(), hooks=Reject())
    events = list(agent.run("do it"))
    types = [e["type"] for e in events]
    assert types == ["turn_start", "turn_end", "done"]
    assert "step_start" not in types
    assert backend.call_index == 0  # no model request was made


def test_turn_stopping_hook_ends_turn_early(tmp_path):
    class StopAfterFirstTool(TurnHooks):
        def __init__(self):
            self.stopped = False

        def should_stop(self):
            return self.stopped

    hooks = StopAfterFirstTool()
    # model would keep calling tools forever
    responses = [[
        LLMResponse(type="tool_call", tool_name="list_files", tool_args={"path": "."}, tool_call_id=f"c{i}"),
        LLMResponse(type="done"),
    ] for i in range(10)]
    agent, backend = make_agent(tmp_path, responses, hooks=hooks)

    events = []
    for ev in agent.run("runaway"):
        events.append(ev)
        if ev["type"] == "tool_result":
            hooks.stopped = True

    types = [e["type"] for e in events]
    assert backend.call_index == 1  # only one step ran
    assert types[0] == "turn_start" and types[-1] == "turn_end"
    assert types.count("step_start") == 1
