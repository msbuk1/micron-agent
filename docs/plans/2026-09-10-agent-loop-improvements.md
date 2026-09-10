# Agent Loop Improvements Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Harden Micron's agent loop with five focused improvements learned from OpenHands, LangGraph, Aider, CrewAI, and SWE-agent.

**Architecture:** All changes stay inside the existing seam: `_LoopController` / `_HistoryCompactor` internals in `micron/agent.py`, `ToolRegistry.call` in `micron/tools/registry.py`, plus three new `AgentConfig` fields. No async, no event bus, no new dependencies. Generator-based streaming is untouched.

**Tech Stack:** Python 3.11, stdlib only (`concurrent.futures`, `time`), pytest with existing `FakeBackend` pattern in `tests/test_agent.py`.

**Baseline:** 385 tests pass (`micron/.venv/bin/python -m pytest tests/ -q`). Python: `micron/.venv/bin/python`. Run all commands with `workdir=/home/matt/micron`.

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Retry LLM only when zero text yielded in that iteration | Already-streamed text cannot be unsent; setup-time failures (connection refused, transient 500) are the common local-model case and have zero yielded text |
| Tool timeout via `concurrent.futures` thread, not `signal.alarm` | `signal.alarm` is main-thread-only and breaks under the TUI/server; threads work everywhere |
| Monologue detection NOT implemented | Investigated: in Micron's loop, zero tool calls yields `done` + return, so text-only output cannot infinite-loop. Documented in code comment instead |
| Compactor stays extractive (no LLM summarizer) | Aider-style LLM summarization needs a model call inside the loop; recursive extractive compression + token-aware budgeting gets 80% of the benefit with zero new failure modes |
| New `AgentConfig` fields need updating the explicit rebuild in `MicronAgent.__init__` (`micron/agent.py:184-193`) | That block reconstructs `AgentConfig` field-by-field; any new field silently drops to default unless added there |

---

## Slice 1: Final-iteration nudge (IsLastStep, from LangGraph)

**Objective:** Tell the model when it is on its last tool iteration so it wraps up instead of calling more tools.

### Task 1: Failing test for nudge injection

**Objective:** Prove the last-iteration LLM call sees a wrap-up instruction.

**Files:**
- Test: `tests/test_agent.py` (append new test)

**Step 1: Write failing test**

```python
def test_final_iteration_nudge_injected(tmp_path):
    """On the last allowed iteration the agent appends a wrap-up nudge."""
    from micron.llm import LLMResponse
    ctx = tmp_path / "context"
    (ctx / "skills").mkdir(parents=True, exist_ok=True)
    backend = FakeBackend([
        [LLMResponse(type="tool_call", tool_name="read_file",
                     tool_args={"path": "a.txt"}, tool_call_id="c1"),
         LLMResponse(type="done", content="")],
        [LLMResponse(type="text", content="final answer"),
         LLMResponse(type="done", content="")],
    ])
    agent = make_agent(tmp_path, backend.responses)
    agent.config.max_tool_iterations = 2
    agent._loop.reset(max_iterations=2)
    list(agent.run("hello"))
    last_messages = backend.messages_history[-1]
    assert any("final answer now" in (m.get("content") or "")
               for m in last_messages), \
        f"nudge missing in: {last_messages}"
```

Note: `make_agent` and `FakeBackend` already exist in `tests/test_agent.py:14-80`. The helper signature is `make_agent(tmpdir, responses, **kwargs)`; it builds its own backend internally, so adapt: pass responses through and read `agent.llm.messages_history`. Check the existing helper before writing (lines 68-100) and match its actual return shape.

**Step 2: Run test to verify failure**

Run: `.venv/bin/python -m pytest tests/test_agent.py::test_final_iteration_nudge_injected -v`
Expected: FAIL — assertion "nudge missing"

**Step 3: Commit test**

```bash
git add tests/test_agent.py
git commit -m "test: final-iteration nudge expectation (red)"
```

### Task 2: Implement nudge constant + injection

**Objective:** Append wrap-up nudge to the LLM message list on the final iteration only.

**Files:**
- Modify: `micron/agent.py:346-376` (`_run_with_messages` loop head)

**Step 1: Add module-level constant near `_LoopController`**

```python
FINAL_ITERATION_NUDGE = (
    "This is your FINAL tool iteration. You MUST produce a final answer now — "
    "do not call more tools. Summarize what you found and answer the user."
)
```

**Step 2: Inject on last iteration**

In `_run_with_messages`, at the top of the `while` loop, replace the direct `self.llm.stream_chat(messages=messages, ...)` call with:

```python
if tool_iterations == self.config.max_tool_iterations - 1:
    llm_messages = messages + [{"role": "user", "content": FINAL_ITERATION_NUDGE}]
else:
    llm_messages = messages
for response in self.llm.stream_chat(
    messages=llm_messages,
    ...
```

Important: build a new list (`messages + [...]`), never mutate `messages` in place — the nudge must not persist into history.

**Step 3: Run test to verify pass**

Run: `.venv/bin/python -m pytest tests/test_agent.py::test_final_iteration_nudge_injected -v`
Expected: PASS

**Step 4: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 386 passed

**Step 5: Commit**

```bash
git add micron/agent.py tests/test_agent.py
git commit -m "feat: final-iteration wrap-up nudge"
```

### Task 3: Edge test — single-iteration config still nudges

**Objective:** With `max_tool_iterations=1` the single call is also the last, so it must carry the nudge.

**Files:**
- Test: `tests/test_agent.py`

**Step 1: Write test** — same shape as Task 1 but `max_tool_iterations=1` and a text-only response; assert nudge present in `messages_history[0]`.

**Step 2: Run** — Expected: PASS (Task 2 implementation already covers it; this locks the behavior).

**Step 3: Commit**

```bash
git add tests/test_agent.py
git commit -m "test: nudge present with max_tool_iterations=1"
```

---

## Slice 2: Short-pattern loop detection (A-B-A-B, from OpenHands StuckDetector)

**Objective:** Catch alternating/rotating tool patterns that fingerprint-dedup misses because all fingerprints are unique.

### Task 4: Failing test for A-B-A-B alternation

**Objective:** `detect_loop` returns True for a 4-call A-B-A-B sequence.

**Files:**
- Test: `tests/test_agent.py`

**Step 1: Write failing test**

```python
def test_detect_alternating_pattern(tmp_path):
    agent = make_agent(tmp_path, [[LLMResponse(type="done", content="")]])
    a = ToolCall(name="read_file", args={"path": "a.txt"}, call_id="1")
    b = ToolCall(name="read_file", args={"path": "b.txt"}, call_id="2")
    assert agent._loop.detect_loop([a]) is False
    assert agent._loop.detect_loop([b]) is False
    assert agent._loop.detect_loop([a]) is False
    assert agent._loop.detect_loop([b]) is True  # A-B-A-B
```

**Step 2: Run** — Expected: FAIL (returns False on the 4th call; current code needs 6 history entries with <=2 unique).

**Step 3: Commit (red)**

```bash
git add tests/test_agent.py
git commit -m "test: A-B-A-B alternation detection (red)"
```

### Task 5: Implement short-pattern check

**Objective:** Detect 4-alternation and 6-rotation (A-B-C-A-B-C) in `_LoopController.detect_loop`.

**Files:**
- Modify: `micron/agent.py:95-107` (`_LoopController.detect_loop`)

**Step 1: Implement**

Current code appends fingerprints to `self.tool_history` then checks last-6. Insert after the extend, before the existing last-6 check:

```python
# Short alternating pattern: A-B-A-B (needs only 4 entries).
if len(self.tool_history) >= 4:
    last4 = self.tool_history[-4:]
    if (len(set(last4)) == 2 and last4[0] == last4[2]
            and last4[1] == last4[3]):
        return True
# Rotation: A-B-C-A-B-C.
if len(self.tool_history) >= 6:
    last6 = self.tool_history[-6:]
    if last6[:3] == last6[3:] and len(set(last6)) == 3:
        return True
```

Keep the existing intra-batch duplicate check and last-6 `<=2 unique` check untouched.

Also add a code comment documenting the investigated-and-rejected monologue counter:

```python
# NOTE: no text-monologue counter. Zero tool calls yields done+return,
# so text-only output cannot infinite-loop in this architecture.
```

**Step 2: Run new test** — Expected: PASS.

**Step 3: Run full suite** — Expected: all pass (existing loop tests in `tests/test_agent.py` must stay green; the new checks only add True cases for patterns the old code returned False on below 6 entries — verify `test_loop_detection`-style tests still pass).

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all passed

**Step 4: Commit**

```bash
git add micron/agent.py tests/test_agent.py
git commit -m "feat: short-pattern loop detection (A-B-A-B, rotation)"
```

### Task 6: Non-pattern regression test

**Objective:** Prove legitimate varied sequences (A-B-C-D) do NOT trip detection.

**Files:**
- Test: `tests/test_agent.py`

**Step 1: Write test** — four distinct tool calls return False throughout.

**Step 2: Run** — Expected: PASS.

**Step 3: Commit**

```bash
git add tests/test_agent.py
git commit -m "test: varied sequence is not a loop"
```

---

## Slice 3: Tool timeouts (layered timeouts, from SWE-agent)

**Objective:** A hung tool can no longer block the agent loop forever. Default 120s per call, configurable.

### Task 7: Failing test for ToolRegistry timeout

**Objective:** `ToolRegistry.call` raises `TimeoutError` when a tool exceeds its budget.

**Files:**
- Test: `tests/test_registry.py` (check existing file first; create if missing)

**Step 1: Write failing test**

```python
import time

def test_tool_call_timeout():
    from micron.tools.registry import ToolRegistry
    reg = ToolRegistry()
    def slow():
        time.sleep(5)
        return "done"
    reg.register(name="slow", func=slow, description="slow",
                 parameters={"type": "object", "properties": {}})
    import pytest
    with pytest.raises(TimeoutError):
        reg.call("slow", timeout=0.2)
```

**Step 2: Run** — Expected: FAIL (no timeout param; sleeps full 5s then returns — use `-x` and expect slow pass, not TimeoutError).

Run: `.venv/bin/python -m pytest tests/test_registry.py::test_tool_call_timeout -v`
Expected: FAIL

**Step 3: Commit (red)**

```bash
git add tests/test_registry.py
git commit -m "test: tool call timeout (red)"
```

### Task 8: Implement timeout in ToolRegistry

**Objective:** Run tool funcs in a worker thread with a deadline.

**Files:**
- Modify: `micron/tools/registry.py:53-57`

**Step 1: Implement**

```python
import concurrent.futures

def call(self, name: str, **kwargs) -> Any:
    """Execute a tool by name.

    `timeout` (seconds) may be passed as a kwarg; it is consumed here,
    never forwarded to the tool function. Raises TimeoutError on expiry.
    """
    if name not in self._tools:
        raise ValueError(f"Tool not found: {name}")
    timeout = kwargs.pop("timeout", None)
    func = self._tools[name].func
    if timeout is None:
        return func(**kwargs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as e:
            raise TimeoutError(
                f"Tool '{name}' timed out after {timeout}s"
            ) from e
```

YAGNI note: no per-tool default registry timeout yet — the agent passes its config value per call (Task 10). `timeout=None` preserves today's synchronous behavior exactly.

**Step 2: Run test** — Expected: PASS, fast (<2s).

**Step 3: Run full suite** — Expected: all passed.

**Step 4: Commit**

```bash
git add micron/tools/registry.py tests/test_registry.py
git commit -m "feat: tool call timeout support"
```

### Task 9: Add `tool_timeout` to AgentConfig (+ rebuild fix)

**Objective:** `AgentConfig.tool_timeout: float = 120.0`, honored through both read and write execution paths.

**Files:**
- Modify: `micron/agent.py:36-44` (AgentConfig dataclass)
- Modify: `micron/agent.py:184-193` (explicit rebuild block — MUST add the new field or it silently resets)

**Step 1: Add field**

```python
@dataclass
class AgentConfig:
    ...
    max_tool_iterations: int = 8
    tool_timeout: float = 120.0
    ...
```

**Step 2: Update rebuild block** — add `tool_timeout=config.tool_timeout,` to the `AgentConfig(...)` reconstruction.

**Step 3: Pass timeout at call sites** — `micron/agent.py:441` (`self.tools.call(tc.name, **tc.args)`) and `:508` (in `_execute_tool_calls`):

```python
result = self.tools.call(tc.name, timeout=self.config.tool_timeout, **tc.args)
```

Careful: `timeout` must precede `**tc.args` so a tool arg literally named `timeout` would collide — no builtin tool has such an arg (verify with a quick grep for `"timeout"` in `micron/tools/builtin.py` before editing).

**Step 4: Test** — write test: agent with `tool_timeout=0.2` and a registered slow read tool yields a `tool_error` event containing "timed out" (not a hang). Use `make_agent` + `agent.tools.register(...)` then `list(agent.run(...))` with FakeBackend returning the slow tool call.

**Step 5: Run full suite** — Expected: all passed.

**Step 6: Commit**

```bash
git add micron/agent.py tests/test_agent.py
git commit -m "feat: configurable tool timeout (default 120s)"
```

---

## Slice 4: LLM retry with backoff (from Aider)

**Objective:** Survive transient LLM failures (connection refused, 500s from local server) with up to 2 retries and exponential backoff, but only when nothing was streamed yet in that iteration.

### Task 10: Failing test for retry-on-setup-failure

**Objective:** A backend that raises on first `stream_chat` then succeeds produces a normal answer with no error event.

**Files:**
- Test: `tests/test_agent.py`

**Step 1: Write failing test**

```python
def test_llm_retry_on_transient_failure(tmp_path):
    from micron.llm import LLMResponse
    ctx = tmp_path / "context"
    (ctx / "skills").mkdir(parents=True, exist_ok=True)
    backend = FakeBackend([[LLMResponse(type="text", content="recovered"),
                            LLMResponse(type="done", content="")]])
    orig = backend.stream_chat
    calls = {"n": 0}
    def flaky(messages, tools=None, temperature=0.1, max_tokens=2048):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("refused")
        yield from orig(messages, tools=tools, temperature=temperature,
                        max_tokens=max_tokens)
    backend.stream_chat = flaky
    from micron.agent import MicronAgent, AgentConfig
    agent = MicronAgent(config=AgentConfig(
        context_dir=str(ctx), provider="fake", model="fake-model",
        llm_kwargs={"backend": backend}))
    events = list(agent.run("hello"))
    assert not any(e["type"] == "error" for e in events)
    assert any(e.get("content") == "recovered" for e in events
               if e["type"] == "text")
```

Check `make_agent`'s actual construction path first — the goal is injecting the flaky backend; adapt to whatever the helper supports (it accepts `**kwargs` into `llm_kwargs`, and backend may be reachable as `agent.llm` for monkeypatching after construction, which is simpler: build agent normally, then wrap `agent.llm.stream_chat`).

**Step 2: Run** — Expected: FAIL (error event, no recovery).

**Step 3: Commit (red)**

```bash
git add tests/test_agent.py
git commit -m "test: LLM transient retry (red)"
```

### Task 11: Implement `_stream_chat_with_retry` helper

**Objective:** Retry generator that re-invokes `stream_chat` on exception when nothing yielded yet.

**Files:**
- Modify: `micron/agent.py` (new private method on `MicronAgent`; use in `_run_with_messages:371`)

**Step 1: Add config fields**

```python
# AgentConfig additions:
llm_retries: int = 2
llm_retry_base_delay: float = 0.25
```

+ rebuild block update (same gotcha as Task 9).

**Step 2: Implement helper**

```python
import time  # top of file

def _stream_chat_with_retry(self, messages, tools, temperature, max_tokens):
    """Yield from llm.stream_chat, retrying transient failures.

    Retries only when NOTHING was yielded yet in this attempt (setup-time
    failure). Mid-stream failures propagate as error events as today —
    already-yielded text cannot be unsent.
    """
    import time as _time
    delay = self.config.llm_retry_base_delay
    for attempt in range(self.config.llm_retries + 1):
        yielded_anything = False
        try:
            for response in self.llm.stream_chat(
                messages=messages, tools=tools,
                temperature=temperature, max_tokens=max_tokens,
            ):
                yielded_anything = True
                yield response
            return
        except Exception:
            if yielded_anything or attempt >= self.config.llm_retries:
                raise
            _time.sleep(delay)
            delay *= 2
```

**Step 3: Use it** — in `_run_with_messages`, replace `for response in self.llm.stream_chat(` with `for response in self._stream_chat_with_retry(`. The existing `elif response.type == "error"` branch stays as the path for backend-returned (non-exception) errors and mid-stream exceptions.

**Step 4: Run new test** — Expected: PASS.

**Step 5: Run full suite** — Expected: all passed.

**Step 6: Commit**

```bash
git add micron/agent.py tests/test_agent.py
git commit -m "feat: retry transient LLM failures with backoff"
```

### Task 12: No-retry regression test (mid-stream failure)

**Objective:** Lock the documented boundary: exception AFTER first chunk propagates (error event), no duplicate retry.

**Files:**
- Test: `tests/test_agent.py`

**Step 1: Write test** — flaky backend yields one text chunk then raises; assert an `error` event appears and the text chunk appears exactly once.

**Step 2: Run** — Expected: PASS.

**Step 3: Commit**

```bash
git add tests/test_agent.py
git commit -m "test: mid-stream failure does not retry"
```

---

## Slice 5: Token-aware recursive compactor (from Aider ChatSummary)

**Objective:** `_HistoryCompactor` sizes history by estimated tokens (not message count), recurses when one pass is not enough, and exposes `keep_recent` via config.

### Task 13: Failing test for token-aware compression

**Objective:** A few very long messages trigger compression even though message count is below the old threshold.

**Files:**
- Test: new `tests/test_compactor.py` (small focused file; compactor is a pure unit)

**Step 1: Write test**

```python
from micron.agent import _HistoryCompactor

def test_compress_triggers_on_tokens_not_count():
    c = _HistoryCompactor(keep_recent=8, max_tokens=2000)
    history = [
        {"role": "user", "content": "x" * 5000},
        {"role": "assistant", "content": "y" * 5000},
        {"role": "user", "content": "hi"},
    ]
    assert c.should_compress(history) is True
    out = c.compress(history)
    assert len(out) < len(history) or out[0]["content"].startswith("Previous conversation")
```

**Step 2: Run** — Expected: FAIL (`should_compress` counts messages; also `max_tokens` param does not exist).

**Step 3: Commit (red)**

```bash
git add tests/test_compactor.py
git commit -m "test: token-aware compactor (red)"
```

### Task 14: Implement token-aware + recursive compactor

**Objective:** Estimate tokens as `len(content)//4`, compress oldest-first until under budget, recurse max depth 3.

**Files:**
- Modify: `micron/agent.py:49-78` (`_HistoryCompactor`)

**Step 1: Implement**

```python
class _HistoryCompactor:
    """Pure history compression — mirrors previous _compress_history."""

    def __init__(self, keep_recent: int = 8, max_tokens: int = 6000,
                 max_depth: int = 3):
        self.keep_recent = keep_recent
        self.max_tokens = max_tokens
        self.max_depth = max_depth

    @staticmethod
    def _tokens(msgs: list[dict]) -> int:
        total = 0
        for m in msgs:
            total += len(str(m.get("content") or "")) // 4
            for tc in m.get("tool_calls") or []:
                total += len(str(tc)) // 4
        return total

    def compress(self, history, keep_recent=None, _depth=0):
        keep = keep_recent if keep_recent is not None else self.keep_recent
        if len(history) <= keep and self._tokens(history) <= self.max_tokens:
            return history
        # Split: summarize oldest chunk, keep the tail; recurse if still over.
        split = max(1, len(history) - keep)
        old, recent = history[:-keep] or history[:split], history[-keep:]
        ...same per-message summarization as today for `old`...
        summary = "Previous conversation summary:\n" + "\n".join(parts)
        out = [{"role": "user", "content": summary}] + recent
        if _depth < self.max_depth and self._tokens(out) > self.max_tokens and len(out) > 2:
            return self.compress(out, keep_recent=keep, _depth=_depth + 1)
        return out

    def should_compress(self, history) -> bool:
        if not history:
            return False
        return len(history) > 12 or self._tokens(history) > self.max_tokens
```

Keep the existing per-message rendering (`[used tools: ...]`, `[tool result]`, 200-char truncation) verbatim — only the trigger and structure change.

**Step 2: Wire config** — `MicronAgent.__init__:239` becomes:

```python
self._compactor = _HistoryCompactor(
    keep_recent=getattr(config, "history_keep_recent", 8))
```

And add `history_keep_recent: int = 8` to `AgentConfig` + rebuild block (same gotcha).

**Step 3: Run new test + full suite** — Expected: all passed.

**Step 4: Commit**

```bash
git add micron/agent.py tests/test_compactor.py
git commit -m "feat: token-aware recursive history compactor"
```

### Task 15: Existing-behavior lock test

**Objective:** Short history under budget passes through untouched (guards against over-compression).

**Files:**
- Test: `tests/test_compactor.py`

```python
def test_short_history_untouched():
    c = _HistoryCompactor()
    history = [{"role": "user", "content": "hi"}]
    assert c.compress(history) == history
    assert c.should_compress(history) is False
```

Run, expect PASS, commit:

```bash
git add tests/test_compactor.py
git commit -m "test: compactor leaves short history alone"
```

---

## Slice 6: Docs + cleanup

### Task 16: Update README/docs + final verification

**Objective:** Document the three new `AgentConfig` fields and behavior changes.

**Files:**
- Check: `README.md` (config section), `PLAN.md` / `SLICE_PLAN.md` if they list agent behavior — keep in sync per repo convention.

**Step 1:** Add `tool_timeout`, `llm_retries`, `history_keep_recent` to any config table; one line each on the nudge + timeout behavior.

**Step 2:** Run FULL suite + quick smoke:

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 385 + ~8 new = ~393 passed

**Step 3: Commit**

```bash
git add README.md PLAN.md SLICE_PLAN.md
git commit -m "docs: agent loop improvements config"
```

---

## Verification Checklist

- [ ] `.venv/bin/python -m pytest tests/ -q` — all pass (~393)
- [ ] Nudge: last-iteration LLM call contains "final answer now"
- [ ] A-B-A-B across 4 calls → "Loop detected. Stopping."
- [ ] Slow tool + small `tool_timeout` → `tool_error` with "timed out", no hang
- [ ] Flaky backend (fail once, then OK) → recovered answer, no error event
- [ ] 3 long messages → `should_compress` True; short history untouched
- [ ] `git log --oneline` shows one commit per task above

## Explicitly Out of Scope (Tier 3, do NOT build)

- Two-model plan/edit pattern, parallel tool execution + resource locking, checkpoint DB persistence, event bus, LLM-based summarization. Micron's simplicity is a feature; revisit only with a concrete failing use case.
