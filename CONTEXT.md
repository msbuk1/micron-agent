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
| `MicronAgent` | `micron/agent.py` | `run(query, history) -> Iterator[Event]` (80% path); `ask(query, history) -> str` (run + process_events); `confirm(writes, *, query, history) -> Iterator[Event]` (resume after `confirmation_required`); `reconfigure/provider,model`/`set_backend`/`unload_model`/`close()` | Deep module — external seam is `MicronAgent(backend, *, config, memory, skills, tools, prompt)` (accepts dependencies). Internal modules `_LoopController` (iteration, `_detect_loop`, 3-strike pivot) and `_HistoryCompactor` (`should_compress`/`compress`) hide loop state. `create_agent(**kwargs, backend, memory, ...)` factory wires `WorkspaceFS`-style local deps. Yields `EventType` events; `set_backend`/`reconfigure` swaps LLM via `create_backend`. Injecting `sessions` (SessionLogger with an active session) makes the log the authority: model history is derived via `derive_messages`, settled output commits as `message` entries, failed/cancelled streams as log-only `attempt` entries, and `_verify_projection` asserts model-visible content is reconstructable from the log (issue #20). |
| `Memory` | `micron/memory.py` | `add / search / get / delete / tag / list / __len__` | JSONL file at `<context>/memory/memories.jsonl`. Sole document store is `TFIDFIndex`; time-decay + importance boost applied in `Memory._score`. |
| `TFIDFIndex` | `micron/search.py` | `add / score / search / docs / get_doc / clear` | Pure-Python TF-IDF. Used by `Memory` and by the `search_knowledge` tool via the shared `search.py`. |
| `ToolDescriptor` | `micron/tools/decorator.py` | `name, description, func, parameters, write` | One descriptor per `@tool`-decorated function. The decorator's global `_registry` is populated on import. |
| `ToolRegistry` | `micron/tools/registry.py` | `register / call / get / is_write / schemas / all / list` | Holds executable tools. Seeded from the decorator registry at agent construction (code-wins dedup). |
| `@tool` | `micron/tools/decorator.py` | `@tool(name, description, write=False, **param_descs)` | Shared by built-ins (`micron/tools/builtin.py`) and user plugins (`context/plugins/*.py`). Auto-derives JSON schema from the function signature. |
| `SkillLoader` | `micron/skills.py` | `load_all / get / all / schemas / reload / add_plugin` | Loads markdown skills (flat `.md` + Hermes-style `SKILL.md` directories). `add_plugin(td)` synthesises a `Skill` from a `ToolDescriptor` so plugin tools appear in the prompt. |
| `LLMBackend` | `micron/llm.py` | `stream_chat(messages, tools, temperature, max_tokens) -> Iterator[LLMResponse]`; `is_available()`; `unload()` | Abstract. Adapters: `LlamaCppBackend`, `OllamaBackend`, `OpenAICompatibleBackend`. `LLMResponse.type` ∈ `text / reasoning / tool_call / done / error`. |
| `OllamaToolAdapter` | `micron/llm.py` | `to_ollama_tools(schemas) / needs_native_tools(model_name)` | Pure functions, not a backend. Format conversion + model detection for Ollama native tool calling. |
| `PromptBuilder` | `micron/prompt.py` | `build_system_prompt(query) -> str` | Composes persona + memory + knowledge + tools + skill instructions. Reads tool list from the `ToolRegistry` when given one. |
| `SessionLogger` | `micron/sessions.py` | `start_session / log_message / log_attempt / log_turn / end_session / list_sessions / read_entries / read_session / derive_messages / get_session_context / resume_session / format_version` | Append-only JSONL log at `<context>/sessions/` — the source of truth for model history (issue #20). `log_message` commits settled model-visible content; `log_attempt` records failed/retried/cancelled streams log-only (never model-visible); `derive_messages` is the projection seam resume/fork/transcript all read through. Header carries `format_version` (v1 `turn` entries migrate forward-only at read time; committed generations never rewritten in place). `log_turn` is the legacy audit-trail shim. `fork_session(parent_id, *, max_messages, child_id)` forks a session into a child seeded purely from the parent's `derive_messages` projection (last `max_messages` settled messages; `None` = all) — child header carries a `parent` link, attempts never carry over, parent log untouched (issue #21). |
| `process_events` | `micron/events.py` | `process_events(generator, **callbacks) -> EventResult` | Walks an agent generator, dispatches each event to its callback, returns accumulated text and pending writes. |
| `TextToolCallParser` | `micron/text_tool_parser.py` | `feed(chunk) -> Iterator[dict]`; `flush() -> Iterator[dict]` | Stateful, SAX-style. Owns the streaming buffer the agent used to manage itself. Yields `{"type": "text", ...}` and `{"type": "tool_call", ...}`. Constructed per tool-iteration with the tool schema list. |
| `strip_tool_call_markup` | `micron/text_tool_parser.py` | `strip_tool_call_markup(text) -> str` | Module-level. Used by the CLI's `_strip_thinking` to remove tool-call-looking syntax before printing. Shares regexes with `TextToolCallParser` so the two never drift. |
| `coerce_param` | `micron/text_tool_parser.py` | `coerce_param(raw, prop_schema) -> Any` | Module-level. Converts a string to the JSON-schema type of the param. Falls back to the raw string on parse failure. |
| `parse_streaming_tool_calls` | `micron/llm.py` | `parse_streaming_tool_calls(delta_iter) -> Iterator[LLMResponse]` | Module-level. Buffers tool-call deltas from any LLM backend stream, emits completed `tool_call` and `text` events. Replaces three duplicate buffering patterns in `LlamaCppBackend`, `OllamaBackend`, and `OpenAICompatibleBackend`. |
| `CommandPolicy` | `micron/tools/command_policy.py` | `evaluate(args) -> Decision` | Pure computation. Evaluates a shell command argument list against the blocklist and flag-scan rules. Returns `Allow`, `Deny(reason)`, or `Limit(cpu, memory, procs, files)`. Tested with synthetic args, no subprocess. `evaluate_command(cmd)` is the shared parse+evaluate entry for raw command strings. |
| `ToolListener` / `ListenerRegistry` | `micron/tools/pipeline.py` | `pre_execute(inv, next) / post_execute(inv, result, next)`; `ListenerRegistry.add/run_pre/run_post` | Waterfall tool pipeline (ADR 0008). Call `next()` to delegate; return without it to short-circuit (pre: deny → `tool_error` via `ErrorFormat`; post: replace result). `CommandPolicyListener` routes `run_command` denial through pre-execute. Wired into `ToolRegistry.call` (`add_listener`/`listeners`), which emits `tool_pre`/`tool_post`/`tool_error` events. |
| `SlashCommandRegistry` | `micron/slash.py` | `register / add / get / all / dispatch(query) -> SlashCommandResult / help_text` | Transport-agnostic `/command` dispatcher. Handlers take `list[str]` args, return a `SlashCommandResult` with `text` and an `extras` dict for transport-specific flags. Decorator-style and imperative register both supported. |
| `CommandDispatcher` | `micron/tui/commands.py` | `handle(cmd) -> CommandResult` | TUI adapter wrapping `SlashCommandRegistry`. All commands route through the registry; `handle` is a thin translation layer mapping `SlashCommandResult.extras` onto Textual `Message` fields. No if/elif ladder (post-issues #2–#4). |
| `ModelPickerScreen` | `micron/tui/screens/models.py` | `ModelPickerScreen(entries)`, dismisses with `{"provider", "model"}` | Modal opened by `/model` (alias `/models`). Renders provider/model/metadata rows as a `ListView`; selecting a row dismisses with the chosen pair, which the app swaps via `CommandDispatcher.switch_model` and reflects in the status bar. |
| `WorkspaceFS` | `micron/workspace.py` | `read(path, *, offset, limit, max_bytes) -> str`; `write(path, content, *, create_dirs, mode, verify) -> Path`; `edit(path, old, new) -> int`; `patch(path, patches) -> int`; `delete(path) -> TrashEntry`; `trash() -> list[TrashEntry]`; `restore(name) -> Path`; `undo(path) -> Path`; `list(path) -> list[DirEntry]`; `tree(path, max_depth, show_files, ext) -> str` | Deep module owning workdir containment (`_resolve`), atomic verified writes (`_verify`), `.trash`/`.bak` lifecycle, truncation and directory enumeration. Single external seam `WorkspaceFS(root)` — injected `Path` in tests (`tmp_path`), otherwise `MICRON_WORKDIR`/`Config`. `micron/tools/builtin.py` tool functions are thin adapters delegating to a singleton `WorkspaceFS`; `_get_trash_dir`/`TIMESTAMP_FMT` remain as compat shims. |
| `KnowledgeIndex` | `micron/knowledge.py` | `prompt_context(query, *, k=5, budget=8000) -> str`; `search(query, *, k=5) -> list[KnowledgeHit]`; `get/docs/reload/size` | Deep module owning knowledge discovery, YAML/title/whitespace + Obsidian `[[wikilink|alias]]`/`![[embed]]` parse, subfolder `**/*.md` glob, `TFIDFIndex` lifecycle, mtime snapshot + budget packing. Cache isolation: `knowledge_dir` inside `context` → `.knowledge_index.*` alongside; external vault (`MICRON_KNOWLEDGE_DIR`/`knowledge_dir`) → cache in `context_dir` to keep vault clean. `TFIDFIndex` internally. `PromptBuilder` + `search_knowledge` are thin adapters. Single seam `KnowledgeIndex(knowledge_dir: Path|None, *, context_dir: Path|None)` local-substitutable via `tmp_path` with symlink `~/vault` support. |
| `RuntimeConfig` | `micron/config.py` | `Config.runtime() -> RuntimeConfig`; `as_dict()/for_agent()/for_backend()/replace()/fake()` | Typed viewport over `Config` — hides `providers` dict hoisting. `resolve_runtime()` kept as shim. Frozen dataclass. |
| `RateLimiter` / `AuthPolicy` | `micron/policy.py` | `RateLimiter.from_config()->allow()/check()->RateLimited`; `AuthPolicy.from_config()->is_valid()/allows()/check()` | In-process gate policies hiding deque window + `hmac.compare_digest`. `clock` injectable for tests. |
| `ErrorFormat` | `micron/error_format.py` | `format_error(exc, hint="", *, tool="")->str`; `ok(msg)->str`; `is_error(str)->bool` | Pure string table hiding `isinstance` + substring precedence + truncation. Single seam for `builtin` adapters and `MicronAgent._friendly_error`; `tools/error_handling.py` is shim. |
| `ServerRuntime` | `micron/server_runtime.py` | `ServerRuntime(config, *, agent, sessions, limiter, auth, preset)` | Ergonomic wrapper hiding `RuntimeConfig`→`create_agent`/`SessionLogger` wiring + `RateLimiter`/`AuthPolicy` globals. The session logger is created before the agent and injected into it at construction (issue #25) — every transport (CLI one-shot, TUI, server) runs the agent with the log as authority; transports never call `log_turn` themselves. `preset` (issue #22) scopes the booted agent's tools via `compose_tools(full_registry(), preset)`; `None`/`"default"` keeps the unscoped path. Local-substitutable via `tmp_path`/`FakeClock`. |
| `ModelCatalog` | `micron/catalog.py` | `list(provider=None)->list[ModelEntry]`; `text(entries, active)->str`; `switch(agent, provider, model)->str` | Deep module owning live fetch (`/api/tags` vs `/models`), fallback chain, price/meta formatting, switch validation. Port `ModelSource.fetch(provider,cfg)->list[dict]` (Http vs Fake). `CommandDispatcher` + `ModelPickerScreen` are thin adapters. |
| `Profiles` | `micron/profiles.py` | `build_composition(config, *, profile, preset, home_patch, overlay_patch, provider, model, temperature, max_tokens) -> Composition`; `boot(composition, *, config, sessions=True) -> Boot`; `apply_patch_layer(rt, patch)`; `canonical_profile(name)`; `canonical_preset(name)`; `full_registry()`; `effective_tools(preset)` | One boot composition for every entry point (CLI one-shot, TUI, server, headless). Ordered patch layers apply deterministically: base (CLI flags) → profile patch → home (`profiles:` section of micron.yaml) → `--patch` overlay file; later layers replace whole rows by id or insert new rows, unknown rows raise. `preset` (issue #22) is a first-class boot input: the composition carries the resolved preset name, `boot` hands it to `ServerRuntime` to scope the agent's tools, unknown names fail loudly, and `--dump-config` shows the preset + effective toolset. `--dump-config` prints the resolved composition (`api_key` redacted). `boot` delegates to `ServerRuntime` — no parallel loader (ADR 0005/0007/0009); `sessions=False` (headless) skips the session logger. `Boot` carries `agent/sessions/limiter/auth/server_runtime`. |
| `budget_join` | `micron/knowledge.py` | `budget_join(chunks, *, budget=8000, label="items", sep)->str` | Pure helper hiding budget + sentinel; used by `KnowledgeIndex.prompt_context` and `PromptBuilder._load_skill_instructions` (no new module). |
| `TurnHooks` / `Inbox` | `micron/turns.py` | `TurnHooks.pre_step(message)->str|None` (rewrite or reject), `TurnHooks.should_stop()->bool`; `Inbox.inject(text)` / `drain()` | Turn/step lifecycle (issue #17). `agent.hooks` is replaceable; `agent.inject()` queues context that lands at the start of the next admitted request. Pass-through by default. |
| `ExecutionWorld` | `micron/execution.py` | `get_world()/set_world()/reset_world()`; world exposes `fs` (WorkspaceFS-compatible), `run(cmd, *, shell, cwd, timeout, limits) -> CommandResult`, `sandbox_wrap(cmd)` | Unified execution seam (issue #19): service definition / provider / consumer. Providers: `LocalWorld` (WorkspaceFS + subprocess with resource limits) and `FakeRemoteWorld` (records calls, never spawns). Selected via `MICRON_EXECUTION_PROVIDER` env or `execution.provider` in micron.yaml (default `local`). File tools resolve `world.fs` via `builtin._ws()`; `run_command` spawns via `world.run`. Sandbox argv-wrapping is applied once, before spawn, by `SandboxListener` in the tool pipeline — never per-tool. |
| `ScopedToolRegistry` | `micron/tools/registry.py` | Same interface as `ToolRegistry` (`register / call / get / is_write / schemas / all / list`) | Isolated view over a parent registry (issue #18): one agent runs with a reduced capability set while the parent keeps the full set. Shares the parent's `Tool` objects; snapshot of parent listeners at construction (scope listener outermost, inherited policy listeners inside). Enforcement lives in the waterfall pipeline via `ToolScopeListener` — out-of-scope calls (even hallucinated ones) resolve against the parent and are denied at pre-execute, rendered as `tool_error` via `ErrorFormat`. `register` outside the scope raises; in-scope re-registration writes through to the parent. |
| `AgentPreset` / `compose_tools` | `micron/profiles.py` | `AGENT_PRESETS` (named presets); `compose_tools(registry, preset) -> ToolRegistry` | Scoping as a first-class composition input (issue #18). A preset is `name` + `tools` tuple (`None` = full set). `compose_tools` returns the registry as-is for full-set presets, a `ScopedToolRegistry` view for scoped ones. Built-ins: `default` (full), `plan` (read/search only). Prompt assembly and `stream_chat(tools=...)` only see in-scope schemas because they read from the view. |

## Event vocabulary

The agent yields events as plain dicts. The canonical names are
`EventType` constants in `micron/events.py`:

- `text` — streamed text chunk from the model.
- `thinking` — reasoning text (where the backend exposes it).
- `tool_start` — a tool invocation is about to run.
- `tool_result` — tool returned successfully.
- `tool_error` — tool raised.
- `confirmation_required` — write tools have been parked awaiting user decision. Payload: `pending_writes: list[{tool_name, args, call_id}]`.
- `tool_pre` / `tool_post` — waterfall pipeline visibility (ADR 0008).
- `turn_start` / `turn_end` — turn lifecycle. A **turn** is zero or more **steps**; it opens before the first input is claimed and closes once nothing is owed. Payload: `turn_id` (and `reason: "rejected"` when a pre-step hook rejected the input).
- `step_start` / `step_end` — step lifecycle. A **step** is one model request plus the tools it calls; steps are indexed from 0.
- `error` — fatal agent error.
- `done` — stream finished.

Turn map (issue #17): `run(message)` opens a turn, claims `message`
through `hooks.pre_step` (rewrite or reject — a rejected/empty first claim
closes the turn with no step), then runs steps; `agent.inject(text)` queues
context in the `Inbox` (`micron/turns.py`) that lands at the start of the
next admitted request, never mid-stream; `hooks.should_stop()` ends the
turn before the next step. CLI, TUI, and server deliberately ignore
turn/step events — `process_events` is the single documented seam where
transports skip them.

The web UI (`micron/static/app.js`) renders these via an `EventRenderer`
class — one method per event type — dispatched by the SSE consumer. The
dispatch shape mirrors `process_events` so both halves of the system stay
in lock-step when a new event type lands. Pipeline visibility events
(`tool_pre`/`tool_post`, ADR 0008) render as tool cards; unknown event
types stay ignored. The transcript endpoint (`GET /session/{id}`) returns
model-visible `turns` plus log-only `attempts` (failed/retried/cancelled
streams) side by side — attempts never enter model history.

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
- `profiles:` (section of micron.yaml) — home patch layer for the boot
  composition (see `Profiles`). Rows are RuntimeConfig field names;
  applied after the profile patch, before `--patch`.

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
| [0008](docs/adr/0008-tool-pipeline.md) | Waterfall tool pipeline (pre/post-execute listeners) | Accepted |
| [0009](docs/adr/0009-profiles-composition.md) | Profiles composition (one boot path, ordered patch layers) | Accepted |

Add a row here when a new ADR is accepted. Don't list draft / rejected
proposals — only those that have shaped the current code.
