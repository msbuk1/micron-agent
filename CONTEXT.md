# CONTEXT — micron domain glossary

Single source of truth for the names used in this codebase. When a new
concept gets a module, add a row here so future reviews and the AI agents
navigating the code can find the right thing.

The architecture vocabulary (module, interface, seam, adapter, leverage,
locality, depth) lives in the `/codebase-design` skill and is not
redefined here.

## Modules

| Name | Lives in | Interface (what callers must know) | Notes |
|---|---|---|---|
| `MicronAgent` | `micron/agent.py` | `run(message, history, stream, confirm, pending_tool_calls) -> Iterator[Event]` | Composes memory, skills, tools, llm, prompt. Yields typed events; event names are the `EventType` constants in `micron/events.py`. |
| `Memory` | `micron/memory.py` | `add / search / get / delete / tag / list / __len__` | JSONL file at `<context>/memory/memories.jsonl`. Sole document store is `TFIDFIndex`; time-decay + importance boost applied in `Memory._score`. |
| `TFIDFIndex` | `micron/search.py` | `add / score / search / docs / get_doc / clear` | Pure-Python TF-IDF. Used by `Memory` and by the `search_knowledge` tool via the shared `search.py`. |
| `ToolDescriptor` | `micron/tools/decorator.py` | `name, description, func, parameters, write` | One descriptor per `@tool`-decorated function. The decorator's global `_registry` is populated on import. |
| `ToolRegistry` | `micron/tools/registry.py` | `register / call / get / is_write / schemas / all / list` | Holds executable tools. Seeded from the decorator registry at agent construction (code-wins dedup). |
| `@tool` | `micron/tools/decorator.py` | `@tool(name, description, write=False, **param_descs)` | Shared by built-ins (`micron/tools/builtin.py`) and user plugins (`context/plugins/*.py`). Auto-derives JSON schema from the function signature. |
| `SkillLoader` | `micron/skills.py` | `load_all / get / all / schemas / reload / add_plugin` | Loads markdown skills (flat `.md` + Hermes-style `SKILL.md` directories). `add_plugin(td)` synthesises a `Skill` from a `ToolDescriptor` so plugin tools appear in the prompt. |
| `LLMBackend` | `micron/llm.py` | `stream_chat(messages, tools, temperature, max_tokens) -> Iterator[LLMResponse]`; `is_available()`; `unload()` | Abstract. Adapters: `LlamaCppBackend`, `OllamaBackend`, `OpenAICompatibleBackend`. `LLMResponse.type` ∈ `text / reasoning / tool_call / done / error`. |
| `OllamaToolAdapter` | `micron/llm.py` | `to_ollama_tools(schemas) / needs_native_tools(model_name)` | Pure functions, not a backend. Format conversion + model detection for Ollama native tool calling. |
| `PromptBuilder` | `micron/prompt.py` | `build_system_prompt(query) -> str` | Composes persona + memory + knowledge + tools + skill instructions. Reads tool list from the `ToolRegistry` when given one. |
| `SessionLogger` | `micron/sessions.py` | `start_session / log_turn / end_session / list_sessions / read_session / get_session_context` | JSONL session files at `<context>/sessions/`. **Used by CLI; not used by the web server today.** |
| `process_events` | `micron/events.py` | `process_events(generator, **callbacks) -> EventResult` | Walks an agent generator, dispatches each event to its callback, returns accumulated text and pending writes. |
| `TextToolCallParser` | `micron/text_tool_parser.py` | `feed(chunk) -> Iterator[dict]`; `flush() -> Iterator[dict]` | Stateful, SAX-style. Owns the streaming buffer the agent used to manage itself. Yields `{"type": "text", ...}` and `{"type": "tool_call", ...}`. Constructed per tool-iteration with the tool schema list. |
| `strip_tool_call_markup` | `micron/text_tool_parser.py` | `strip_tool_call_markup(text) -> str` | Module-level. Used by the CLI's `_strip_thinking` to remove tool-call-looking syntax before printing. Shares regexes with `TextToolCallParser` so the two never drift. |
| `coerce_param` | `micron/text_tool_parser.py` | `coerce_param(raw, prop_schema) -> Any` | Module-level. Converts a string to the JSON-schema type of the param. Falls back to the raw string on parse failure. |
| `parse_streaming_tool_calls` | `micron/llm.py` | `parse_streaming_tool_calls(delta_iter) -> Iterator[LLMResponse]` | Module-level. Buffers tool-call deltas from any LLM backend stream, emits completed `tool_call` and `text` events. Replaces three duplicate buffering patterns in `LlamaCppBackend`, `OllamaBackend`, and `OpenAICompatibleBackend`. |
| `CommandPolicy` | `micron/tools/command_policy.py` | `evaluate(args) -> Decision` | Pure computation. Evaluates a shell command argument list against the blocklist and flag-scan rules. Returns `Allow`, `Deny(reason)`, or `Limit(cpu, memory, procs, files)`. Tested with synthetic args, no subprocess. |

## Event vocabulary

The agent yields events as plain dicts. The canonical names are
`EventType` constants in `micron/events.py`:

- `text` — streamed text chunk from the model.
- `thinking` — reasoning text (where the backend exposes it).
- `tool_start` — a tool invocation is about to run.
- `tool_result` — tool returned successfully.
- `tool_error` — tool raised.
- `confirmation_required` — write tools have been parked awaiting user decision. Payload: `pending_writes: list[{tool_name, args, call_id}]`.
- `error` — fatal agent error.
- `done` — stream finished.

The web UI's inline JavaScript implements a second handler for the same
event types — the duplication is candidate #2.

## Tools

Built-ins live in `micron/tools/builtin.py`. Each is a `@tool`-decorated
function. `write=True` flags the tools that pause for confirmation. The
24 tools are listed in `README.md` (single source of truth post-slice-23).

## Plugins

A plugin is a Python file in `context/plugins/` that imports `@tool`
from `micron.tools.decorator` and decorates a function. `discover_plugins`
in `micron/plugins/loader.py` scans the directory and returns the new
`ToolDescriptor`s registered by import side-effect. A second agent
construction clears the registry via `clear()`.

## Skills (markdown, distinct from tools)

Two flavours:

- **Knowledge / tool skill** — a single `*.md` file with YAML
  frontmatter (`name`, `description`, `parameters`, optional `write`,
  `module`). After the Skills/Tools split, `module` is dead — tools come
  from `@tool`, not from skill markdown.
- **Procedure skill** — a directory with `SKILL.md`. Loaded on demand
  via the `/skill NAME` CLI command and injected into the next user
  message. May link sibling `.md` files which are inlined into the body.

## Configuration surface

- `micron.yaml` — provider config, rate limits, auth, firecrawl URL,
  write confirmation (`auto_confirm_writes`: `ask` | `allow` | `deny`).
- `Config` (in `micron/config.py`) — **single loader**: defaults → YAML →
  env (`MICRON_*`). Exposes `get_rate_limits`, `get_resource_limits`,
  `get_authentication`, `is_valid_api_key`, `get_provider_config`,
  `resolve_runtime` (flat dict for agent+backend construction),
  `_apply_env_vars` (populates `MICRON_WORKDIR` / `MICRON_CONTEXT_DIR` /
  `MICRON_PROVIDER` / `FIRECRAWL_URL` for tools that read env vars).
  CLI, TUI, and server all use `Config`. The former `__main__.load_config`
  parallel loader has been removed.

## Out-of-band notes

- Web chat is **not** session-persistent. History lives in the browser;
  CLI uses `SessionLogger`. (Slices 25–27 are the planned alignment.)
- `micron/static/` has been removed — the server serves the inline
  `HTML_PAGE` from `server.py`.
- `error_handling.py` defines `handle_error`, `success` — but
  `agent._friendly_error` re-implements the same string-shape coercion.
  One seam, two implementations. (`ToolError` and `format_tool_result`
  were dead and have been removed.)

## Architectural decisions

Recorded in `docs/adr/` (Nygard format: Status / Context / Decision /
Consequences). Read the relevant ADR before refactoring any module it
covers — the decisions are load-bearing for future reviews and
architecture reviews should not re-litigate them.

| ADR | Subject | Status |
|---|---|---|
| [0001](docs/adr/0001-text-tool-call-parser.md) | Stateful incremental parser for text-format tool calls | Accepted |

Add a row here when a new ADR is accepted. Don't list draft / rejected
proposals — only those that have shaped the current code.
