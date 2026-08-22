# ADR 0003 — MicronAgent injected seam + internal LoopController / HistoryCompactor

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** codebase review (design-it-twice P1)
- **Origin:** P1 candidate — `micron/agent.py:47` constructor created `Memory`/`SkillLoader`/`ToolRegistry`/`create_backend` + mix of `_run_with_messages:181`, `_detect_loop:435`, `_compress_history:449`

## Context

`MicronAgent` violated *accept dependencies, don't create them*: `__init__` did `Memory(context_dir/memory)`, `SkillLoader`, `ToolRegistry` seeding from `decorator._registry`, `create_backend`, `PromptBuilder`. Testing the tool loop required a full filesystem + env. The loop itself mixed iteration count, `TextToolCallParser` wiring per iteration, `read` vs `write` split, `confirmation_required` parking, `tool_history` fingerprint dup + `last6≤2` window, 3-strike `STOP and think differently` pivot, history `len>12→keep 8` compression — all in one 120-line generator.

`LLMBackend` already was a real seam (3 adapters + `FakeBackend` in `tests/test_agent.py:14`). `Memory`/`SkillLoader` were local-substitutable via `tmp_path` but not injected. `WorkspaceFS` showed `Path` injection is sufficient for local deps.

## Decision

Keep small external seam, hide loop policy internally:

```python
class MicronAgent:
    def __init__(self, backend: LLMBackend, *, config=AgentConfig(), memory: Memory|None=None, skills: SkillLoader|None=None, tools: ToolRegistry|None=None, prompt: PromptBuilder|None=None): ...
    def run(self, query: str, history=None) -> Iterator[Event]: ...  # 80% path
    def ask(self, query: str, history=None) -> str: ...              # run+process_events
    def confirm(self, writes, *, query="", history=None) -> Iterator[Event]: ...  # resume after confirmation_required
    def reconfigure(provider, model, **kw) -> None: ...  # alias set_backend
    def close() -> None: ...                             # alias unload_model

class _LoopController: tool_history, consecutive_failures, max_iterations, detect_loop(calls)->bool, record_result(has_errors)->pivot|None
class _HistoryCompactor: should_compress(history)->bool, compress(history, keep_recent=8)->history
```

`_LoopController` owns fingerprint `(name, frozenset(args))`, duplicate-in-batch + sliding window, `tool_history` list. `_HistoryCompactor` owns `keep_recent=8`, `[used tools: …]` / `[tool result]` summarization. Both are internal — not at external seam. `create_agent(**kwargs, backend, memory…)` factory wires `WorkspaceFS`-style local deps. Legacy `MicronAgent(AgentConfig(llm_kwargs={"backend": fake}))` kept for compat via `isinstance(config, LLMBackend)` detection.

Rejected: (B) 7-policy composition (`LoopPolicy`/`HistoryStrategy`/`ToolExecutor`/`ParserFactory`/`StreamingPolicy`/`Interceptor`) — 6 hypothetical seams today; (A) single `chat(message,history)` renaming `run` — churn for no leverage. Chose ergonomic C: `run` stays name-stable, `ask` adds leverage for non-stream `server.py:318` branch.

## Consequences

### Positive

- **Testability** — loop/pivot/compression exercised through `MicronAgent(backend=FakeLLM, memory=Memory(tmp_path))` + scripted `list[LLMResponse]`; no env/filesystem reach-through.
- **Locality** — fixing loop false-positive or pivot wording fixes one place.
- **Leverage** — `ask` collapses `server.py` non-stream `process_events(a.run(...))` to one call.

### Negative

- Frozen `AgentConfig` kept mutable for compat (`config.provider` mutation in `set_backend:652`); not frozen despite design intent.
- `MicronAgent` now has two construction shapes — positional `MicronAgent(fake)` and keyword `MicronAgent(backend=…)` — edge handled via `isinstance` branch; documented as compat shim to remove later.
- No `HistoryStore` port — history remains `list[dict]` wire shape for LLM compat; structured `History` dataclass not introduced.
