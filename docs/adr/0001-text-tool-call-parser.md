# ADR 0001 — Stateful incremental parser for text-format tool calls

- **Status:** Accepted
- **Date:** 2026-08-08
- **Deciders:** codebase review (architecture session)
- **Origin:** candidate #1 from the architecture review (`/tmp/architecture-review-20260808T203957Z.html`)

## Context

`MicronAgent` runs against two kinds of LLM backends:

- **API backends** (OpenAI-compatible, Ollama native) — yield typed `tool_call` events in `LLMResponse`.
- **Local models** (llamacpp, Qwen, MiniCPM) that don't support native tool-calling — emit tool calls as text in one of two formats:
  - **function-tag:** `<function name="X">{"a":"b"}</function>[PROMPT_INJECTION]`
  - **name-quote:** `name="X"> name="Y">value`

To handle the second case the agent carried ~100 lines of inline regex (`agent.py:170-183` and `agent.py:425-531` before the refactor):

- A `looks_like_tool_call(text) -> bool` predicate called per streaming chunk.
- A `_parse_text_tool_calls` / `_parse_name_quote_format` / `_parse_function_tag_format` trio called at end of turn.
- A `_coerce_param` helper for type coercion.
- A `text_buffer` string the agent owned and managed itself.

The same patterns were duplicated in `__main__.py._strip_thinking` (lines 60-61 before the refactor) so the CLI could remove tool-call-looking syntax from model output before printing. Two files, two slightly-diverging regexes, one concept.

The pain points were:

- **Locality** — a fix to "what does a tool call look like" had to be made in three files (agent's `looks_like`, agent's parsers, CLI's strip). The strip's regex `</function>` did not match the parser's `[PROMPT_INJECTION]` terminator; that divergence went unnoticed.
- **Testability** — exercising the regexes required standing up a full `MicronAgent` with a fake LLM backend. Two test files (`test_agent.py:168-209`) set up entire agents just to feed text through a regex.
- **State leak** — the agent held `text_buffer` *only* to support the parser's predicate. The buffer's lifetime and clear rules were the predicate's logic in disguise.
- **Inconsistent extract surface** — function-tag and name-quote had separate parser methods with subtly different code paths and an intentional one-vs-many asymmetry baked in (`break` after the first name-quote match).

## Decision

Extract a stateful, SAX-style incremental parser into a new top-level module `micron/text_tool_parser.py`:

```python
class TextToolCallParser:
    def __init__(self, tool_schemas: list[dict]) -> None
    def feed(self, chunk: str) -> Iterator[dict]   # hot path
    def flush(self) -> Iterator[dict]             # cold path
```

The parser owns the streaming buffer the agent used to manage. The agent constructs one parser per tool-iteration and pumps streaming chunks through `feed`. The parser yields two event types: `{"type": "text", "content"}` for chunks safe to surface and `{"type": "tool_call", "name", "args", "call_id"}` for extracted calls. The agent maps `tool_call` to its existing `tool_start` event and converts to its `ToolCall` dataclass at the boundary.

A module-level `strip_tool_call_markup(text) -> str` shares the parser's compiled regexes, replacing the duplicated strip pair in `_strip_thinking`.

`ToolCall` stays in `agent.py`; the parser returns `list[dict]` (dicts with the same shape). The agent converts at the boundary via the new `_consume_parser_events` helper.

### Rejected alternatives

- **Stateless functions + agent-owned buffer (Design A from the design-it-twice).** Three pure functions (`looks_like`, `parse`, `strip`). The agent keeps `text_buffer`. Doesn't fix the buffer leak — `text_buffer` still exists only to support a predicate.
- **Strategy / format Protocol (Design B).** `ToolCallFormat` Protocol with `looks_like` / `parse` / `strip` per format, a composer class. Open/closed for new formats. Over-engineered for two formats; the format count is unlikely to grow without a code-wins dedup or a real new family.
- **Per-text-call `parse(text, tool_schemas)` module-level function.** Same as stateless but with full extraction in one call. Matches the original end-of-turn parse shape. Rejected because the streaming predicate and the end-of-turn parse end up duplicating buffer-state logic.

## Consequences

### Positive

- **Locality.** The text-tool-call patterns live in one file. Fixing "what does a tool call look like" is a one-file change. The `</function>` / `[PROMPT_INJECTION]` divergence evaporates.
- **Testability.** 31 new tests (`tests/test_text_tool_parser.py`) cover the parser as a pure stream-to-events transducer: `list(parser.feed("a", "b", "c")) -> expected events`. No `MicronAgent`, no fake LLM backend, no tempfile.
- **Buffer ownership.** The agent's `text_buffer` and the inline buffer-management touch-points (`agent.py:201`, `:211`, `:222`, `:236` before the refactor) are gone. The agent's streaming loop becomes a pump: `yield from self._consume_parser_events(text_parser.feed(chunk), ...)`.
- **Single interface for the CLI.** `__main__._strip_thinking` calls `strip_tool_call_markup(text)`. The CLI and the agent cannot drift.

### Negative

- **Stateful object.** The parser is stateful; misuse patterns include reusing a parser across turns (forgotten flush) or constructing one with stale schemas. We scope the parser to one tool-iteration so its lifetime matches the buffer's lifetime that already existed implicitly.
- **Slight behavior difference in edge cases.** The original code's `text_buffer` accumulated across chunks; the new parser drops the held content on release (when the next chunk is clearly not a tool call). This matches the original's effective behavior — the held content was already not surfaced to the user — but the parser's buffer transitions are more visible. Two tests pin the pre-existing quirks (function-tag body includes `</function>`, so JSON parse always falls through to name-quote; strip's `[^\n]*` is greedy) so future refactors don't silently "fix" them.
- **Class surface added to the codebase.** The module exposes one class plus three module-level functions. This is more than the single function we started with. Justified by the stateful-streaming pattern; not justified if a future caller wants a one-shot parse.
- **No adapter for the parser.** The parser is in-process; tests run directly against the interface. The four-line `coerce_param` is internal but exposed for completeness.

## Implementation notes

- The parser's `feed` extracts function-tag blocks as soon as the `[PROMPT_INJECTION]` marker arrives, then clears its buffer (matches the original's "suppress text surrounding a parsed tool call" behaviour).
- The parser's `feed` holds on any name-quote partial (`ends with name="X">`) or complete (`name="X"> name="Y">`). The hold is released when a new chunk is clearly not a name-quote continuation. Released holds are dropped, not surfaced — the original code's held content was also not surfaced to the user.
- The parser's `flush` extracts any remaining name-quote call (at most one, matching the original's `break`-after-first behaviour) and emits any leftover buffer content as text.
- The agent gates parser tool_call events on `tools_used_this_turn` (matches the original's `if not pending_calls and ... and not tools_used_this_turn:` end-of-turn parse check). After a read tool has been called, the model is responding to the tool result — not planning new calls.

## Follow-ups

- The `</function>`-in-body and greedy-strip quirks are pinned by tests but unfixed. If a future refactor wants to fix them, it should be a separate ADR.
- The function-tag / name-quote asymmetry (function-tag can yield N calls, name-quote yields at most one) is preserved. Fixing it would touch the parser and the test suite but not the agent.
- Slices 25-27 (CLI/Web alignment) can now share the parser's `strip_tool_call_markup` for any server-side output sanitisation, instead of duplicating the regex pair.
