# 10 — Share streaming tool-call parser across LLM backends

**Status:** ✅ done

**GitHub:** https://github.com/msbuk1/micron-agent/issues/11
**Labels:** `enhancement`, `ready-for-agent`

## What to build

Three LLM backends (`LlamaCppBackend`, `OllamaBackend`, `OpenAICompatibleBackend` in `micron/llm.py`) each carry their own copy of "buffer `tool_call_id`, `name`, `arguments`; parse `arguments` as JSON; yield one `tool_call` per completed call." Extract a single module-level `parse_streaming_tool_calls(delta_iter) -> Iterator[LLMResponse]` and migrate all three backends to use it. Each backend shrinks to its genuinely different piece (chat-format detection, error fallback, native-tool shim).

## Blocked by

None — independent of the other work. **Constraint:** do not reintroduce regex inside `agent.py` (ADR 0001 keeps the text-format parsing in `micron/text_tool_parser.py`).

## Acceptance criteria

- [ ] `parse_streaming_tool_calls` exists as a module-level function with tests
- [ ] All three backends call it instead of buffering inline
- [ ] Each backend's `stream_chat` body shrinks
- [ ] All existing tests pass
