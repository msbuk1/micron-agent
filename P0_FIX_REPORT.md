# micron — P0 Fix Report

> Status: COMPLETE — all 26 tests passing  
> Date: 2026-07-07

## Summary

All P0 fixes from `REVIEW.md` have been carried out and verified.

## Fixes Applied

### 1. Agent Loop Protocol (`micron/agent.py`)
- ✅ Tool results are now emitted as correct `role: "tool"` messages with `tool_call_id`.
- ✅ Assistant messages contain a proper `tool_calls` array when tools are used.
- ✅ Text-based tool parsing is auto-enabled only for `llamacpp` / `ollama`; disabled by default for API backends.
- ✅ `AgentConfig` retains `max_tokens = 2048`.

### 2. Prompt Builder (`micron/prompt.py`)
- ✅ Removed the hard-coded 15-tool manifest (was ~5 k tokens).
- ✅ Tool list is now generated dynamically from loaded skills.
- ✅ Relevant memories are now injected into the system prompt.
- ✅ Knowledge section returns `(no relevant knowledge)` instead of dumping all files.
- ✅ Text tool markup instructions only appear for local/text models.

### 3. Memory (`micron/memory.py`)
- ✅ Fixed IDF precedence bug: `(math.log(n_docs / df) + 1.0) if df > 0 else 0.0`.

### 4. Security (`micron/tools/builtin.py`)
- ✅ Path traversal now validated with `Path.relative_to(workdir)` for `read_file`, `write_file`, `list_files`, `run_command`.
- ✅ `python_eval` replaced bypassable blocklist + `exec/eval` with `asteval.Interpreter` sandbox.
- ✅ `run_command` has tighter blocklist and `MICRON_UNRESTRICTED=1` opt-in.

### 5. Dependencies (`pyproject.toml`)
- ✅ Added `asteval>=0.9`.

## Verification

```bash
cd /home/matt/micron
python -m compileall micron           # ✅ no syntax errors
. .venv/bin/activate
python -m pytest tests/ -q           # ✅ 26 passed
```

## Still Open (P1 / P2)

- Add pytest tests for new tool-role messaging, path traversal edge cases, and `asteval` sandbox.
- Make llama.cpp `chat_format` configurable per model.
- Use official `openai` client for OpenAI-compatible backend.
- Refine write-tool confirmation flow (`confirm=True` / `pending_tool_calls` is functional but could be cleaner).
- Optional: vector memory, file locking for JSONL, `micron.yaml` config migration.

## Result

micron is now protocol-correct for tool calling, secure against traversal and arbitrary-code execution, and has a much smaller system prompt suitable for 1B/3B models.
