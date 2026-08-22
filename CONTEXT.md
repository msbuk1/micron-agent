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
| `MicronAgent` | `micron/agent.py` | `run(query, history) -> Iterator[Event]` (80% path); `ask(query, history) -> str` (run + process_events); `confirm(writes, *, query, history) -> Iterator[Event]` (resume after `confirmation_required`); `reconfigure/provider,model`/`set_backend`/`unload_model`/`close()` | Deep module — external seam is `MicronAgent(backend, *, config, memory, skills, tools, prompt)` (accepts dependencies). Internal modules `_LoopController` (iteration, `_detect_loop`, 3-strike pivot) and `_HistoryCompactor` (`should_compress`/`compress`) hide loop state. `create_agent(**kwargs, backend, memory, ...)` factory wires `WorkspaceFS`-style local deps. Yields `EventType` events; `set_backend`/`reconfigure` swaps LLM via `create_backend`. |
| `Memory` | `micron/memory.py` | `add / search / get / delete / tag / list / __len__` | JSONL file at `<context>/memory/memories.jsonl`. Sole document store is `TFIDFIndex`; time-decay + importance boost applied in `Memory._score`. |
| `TFIDFIndex` | `micron/search.py` | `add / score / search / docs / get_doc / clear` | Pure-Python TF-IDF. Used by `Memory` and by the `search_knowledge` tool via the shared `search.py`. |
| `ToolDescriptor` | `micron/tools/decorator.py` | `name, description, func, parameters, write` | One descriptor per `@tool`-decorated function. The decorator's global `_registry` is populated on import. |
| `ToolRegistry` | `micron/tools/registry.py` | `register / call / get / is_write / schemas / all / list` | Holds executable tools. Seeded from the decorator registry at agent construction (code-wins dedup). |
| `@tool` | `micron/tools/decorator.py` | `@tool(name, description, write=False, **param_descs)` | Shared by built-ins (`micron/tools/builtin.py`) and user plugins (`context/plugins/*.py`). Auto-derives JSON schema from the function signature. |
| `SkillLoader` | `micron/skills.py` | `load_all / get / all / schemas / reload / add_plugin` | Loads markdown skills (flat `.md` + Hermes-style `SKILL.md` directories). `add_plugin(td)` synthesises a `Skill` from a `ToolDescriptor` so plugin tools appear in the prompt. |
| `LLMBackend` | `micron/llm.py` | `stream_chat(messages, tools, temperature, max_tokens) -> Iterator[LLMResponse]`; `is_available()`; `unload()` | Abstract. Adapters: `LlamaCppBackend`, `OllamaBackend`, `OpenAICompatibleBackend`. `LLMResponse.type` ∈ `text / reasoning / tool_call / done / error`. |
| `OllamaToolAdapter` | `micron/llm.py` | `to_ollama_tools(schemas) / needs_native_tools(model_name)` | Pure functions, not a backend. Format conversion + model detection for Ollama native tool calling. |
| `PromptBuilder` | `micron/prompt.py` | `build_system_prompt(query) -> str` | Composes persona + memory + knowledge + tools + skill instructions. Reads tool list from the `ToolRegistry` when given one. |
| `SessionLogger` | `micron/sessions.py` | `start_session / log_turn / end_session / list_sessions / read_session / get_session_context` | JSONL session files at `<context>/sessions/`. Used by the CLI, TUI, and the web server. One session per server lifetime; user turn logged before `chat()`, assistant turn logged after the stream finishes (or after `process_events` for non-streaming). |
| `process_events` | `micron/events.py` | `process_events(generator, **callbacks) -> EventResult` | Walks an agent generator, dispatches each event to its callback, returns accumulated text and pending writes. |
| `TextToolCallParser` | `micron/text_tool_parser.py` | `feed(chunk) -> Iterator[dict]`; `flush() -> Iterator[dict]` | Stateful, SAX-style. Owns the streaming buffer the agent used to manage itself. Yields `{"type": "text", ...}` and `{"type": "tool_call", ...}`. Constructed per tool-iteration with the tool schema list. |
| `strip_tool_call_markup` | `micron/text_tool_parser.py` | `strip_tool_call_markup(text) -> str` | Module-level. Used by the CLI's `_strip_thinking` to remove tool-call-looking syntax before printing. Shares regexes with `TextToolCallParser` so the two never drift. |
| `coerce_param` | `micron/text_tool_parser.py` | `coerce_param(raw, prop_schema) -> Any` | Module-level. Converts a string to the JSON-schema type of the param. Falls back to the raw string on parse failure. |
| `parse_streaming_tool_calls` | `micron/llm.py` | `parse_streaming_tool_calls(delta_iter) -> Iterator[LLMResponse]` | Module-level. Buffers tool-call deltas from any LLM backend stream, emits completed `tool_call` and `text` events. Replaces three duplicate buffering patterns in `LlamaCppBackend`, `OllamaBackend`, and `OpenAICompatibleBackend`. |
| `CommandPolicy` | `micron/tools/command_policy.py` | `evaluate(args) -> Decision` | Pure computation. Evaluates a shell command argument list against the blocklist and flag-scan rules. Returns `Allow`, `Deny(reason)`, or `Limit(cpu, memory, procs, files)`. Tested with synthetic args, no subprocess. |
| `SlashCommandRegistry` | `micron/slash.py` | `register / add / get / all / dispatch(query) -> SlashCommandResult / help_text` | Transport-agnostic `/command` dispatcher. Handlers take `list[str]` args, return a `SlashCommandResult` with `text` and an `extras` dict for transport-specific flags. Decorator-style and imperative register both supported. |
| `CommandDispatcher` | `micron/tui/commands.py` | `handle(cmd) -> CommandResult` | TUI adapter wrapping `SlashCommandRegistry`. All commands route through the registry; `handle` is a thin translation layer mapping `SlashCommandResult.extras` onto Textual `Message` fields. No if/elif ladder (post-issues #2–#4). |
| `ModelPickerScreen` | `micron/tui/screens/models.py` | `ModelPickerScreen(entries)`, dismisses with `{"provider", "model"}` | Modal opened by `/models`. Renders provider/model/metadata rows as a `ListView`; selecting a row dismisses with the chosen pair, which the app swaps via `CommandDispatcher.switch_model` and reflects in the status bar. |
| `WorkspaceFS` | `micron/workspace.py` | `read(path, *, offset, limit, max_bytes) -> str`; `write(path, content, *, create_dirs, mode, verify) -> Path`; `edit(path, old, new) -> int`; `patch(path, patches) -> int`; `delete(path) -> TrashEntry`; `trash() -> list[TrashEntry]`; `restore(name) -> Path`; `undo(path) -> Path`; `list(path) -> list[DirEntry]`; `tree(path, max_depth, show_files, ext) -> str` | Deep module owning workdir containment (`_resolve`), atomic verified writes (`_verify`), `.trash`/`.bak` lifecycle, truncation and directory enumeration. Single external seam `WorkspaceFS(root)` — injected `Path` in tests (`tmp_path`), otherwise `MICRON_WORKDIR`/`Config`. `micron/tools/builtin.py` tool functions are thin adapters delegating to a singleton `WorkspaceFS`; `_get_trash_dir`/`TIMESTAMP_FMT` remain as compat shims. |
| `KnowledgeIndex` | `micron/knowledge.py` | `prompt_context(query, *, k=5, budget=8000) -> str`; `search(query, *, k=5) -> list[KnowledgeHit]`; `get/docs/reload/size` | Deep module owning knowledge discovery, YAML/title/whitespace + Obsidian `[[wikilink|alias]]`/`![[embed]]` parse, subfolder `**/*.md` glob, `TFIDFIndex` lifecycle, mtime snapshot + budget packing. Cache isolation: `knowledge_dir` inside `context` → `.knowledge_index.*` alongside; external vault (`MICRON_KNOWLEDGE_DIR`/`knowledge_dir`) → cache in `context_dir` to keep vault clean. `TFIDFIndex` internally. `PromptBuilder` + `search_knowledge` are thin adapters. Single seam `KnowledgeIndex(knowledge_dir: Path|None, *, context_dir: Path|None)` local-substitutable via `tmp_path` with symlink `~/vault` support. |
| `RuntimeConfig` | `micron/config.py` | `Config.runtime() -> RuntimeConfig`; `as_dict()/for_agent()/for_backend()/replace()/fake()` | Typed viewport over `Config` — hides `providers` dict hoisting. `resolve_runtime()` kept as shim. Frozen dataclass. |
| `RateLimiter` / `AuthPolicy` | `micron/policy.py` | `RateLimiter.from_config()->allow()/check()->RateLimited`; `AuthPolicy.from_config()->is_valid()/allows()/check()` | In-process gate policies hiding deque window + `hmac.compare_digest`. `clock` injectable for tests. |
| `ErrorFormat` | `micron/error_format.py` | `format_error(exc, hint="", *, tool="")->str`; `ok(msg)->str`; `is_error(str)->bool` | Pure string table hiding `isinstance` + substring precedence + truncation. Single seam for `builtin` adapters and `MicronAgent._friendly_error`; `tools/error_handling.py` is shim. |
| `ServerRuntime` | `micron/server_runtime.py` | `ServerRuntime(config, *, agent, sessions, limiter, auth)`; `load(path,**overrides)` | Ergonomic wrapper hiding `RuntimeConfig`→`create_agent`/`SessionLogger` wiring + `RateLimiter`/`AuthPolicy` globals. Local-substitutable via `tmp_path`/`FakeClock`. |
| `ModelCatalog` | `micron/catalog.py` | `list(provider=None)->list[ModelEntry]`; `text(entries, active)->str`; `switch(agent, provider, model)->str` | Deep module owning live fetch (`/api/tags` vs `/models`), fallback chain, price/meta formatting, switch validation. Port `ModelSource.fetch(provider,cfg)->list[dict]` (Http vs Fake). `CommandDispatcher` + `ModelPickerScreen` are thin adapters. |
| `budget_join` | `micron/knowledge.py` | `budget_join(chunks, *, budget=8000, label="items", sep)->str` | Pure helper hiding budget + sentinel; used by `KnowledgeIndex.prompt_context` and `PromptBuilder._load_skill_instructions` (no new module). |

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

The web UI (`micron/static/app.js`) renders these via an `EventRenderer`
class — one method per event type — dispatched by the SSE consumer. The
dispatch shape mirrors `process_events` so both halves of the system stay
in lock-step when a new event type lands.

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
  **Never holds secrets.**
- `auth.yaml` — gitignored secrets file merged over `micron.yaml` per
  provider (see `_deep_merge` in `micron/config.py`). Template in
  `auth.example.yaml`. Auto-discovered next to `micron.yaml`.
- `Config` (in `micron/config.py`) — **single loader**: defaults → YAML →
  auth.yaml → env (`MICRON_*`). Exposes `get_rate_limits`,
  `get_resource_limits`, `get_authentication`, `is_valid_api_key`,
  `get_provider_config`, `resolve_runtime` (flat dict for agent+backend
  construction), `_apply_env_vars` (populates `MICRON_WORKDIR` /
  `MICRON_CONTEXT_DIR` / `MICRON_PROVIDER` / `FIRECRAWL_URL` for tools
  that read env vars). CLI, TUI, and server all use `Config`. The former
  `__main__.load_config` parallel loader has been removed.

## Out-of-band notes

- The web UI lives in `micron/static/{index.html,style.css,app.js}`
  served via FastAPI's `StaticFiles` mounted at `/`. `server.py` no
  longer carries any HTML/JS/CSS markup.
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
| [0002](docs/adr/0002-workspacefs.md) | WorkspaceFS deep module | Accepted |
| [0003](docs/adr/0003-micron-agent.md) | MicronAgent injected seam + LoopController / HistoryCompactor | Accepted |
| [0004](docs/adr/0004-knowledge-index.md) | KnowledgeIndex deep module | Accepted |
| [0005](docs/adr/0005-runtime-gate.md) | RuntimeConfig + RateLimiter / AuthPolicy | Accepted |
| [0006](docs/adr/0006-error-format.md) | ErrorFormat deep module | Accepted |
| [0007](docs/adr/0007-server-runtime.md) | ServerRuntime deep module | Accepted |

Add a row here when a new ADR is accepted. Don't list draft / rejected
proposals — only those that have shaped the current code.
