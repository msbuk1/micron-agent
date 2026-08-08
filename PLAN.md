# Roadmap

**Last Updated:** 2026-08-08
**Status:** 262/262 tests passing · Skills/Tools split shipped · text-tool-call parser shipped · CommandPolicy + streaming parser shipped

The forward-looking plan lives here. Historical slice work is in
`git log`; architectural decisions are in `docs/adr/`.

---

## Project structure

```
micron/
├── CONTEXT.md         # Domain glossary (module names, event vocabulary, config surface)
├── context/           # skills, knowledge, memory, sessions, persona, plugins, uploads
├── docs/adr/          # Architectural Decision Records
├── micron/
│   ├── __main__.py    # CLI + interactive mode
│   ├── agent.py       # Core agent loop
│   ├── config.py      # Unified config loader (YAML + env)
│   ├── events.py      # process_events + EventType vocabulary
│   ├── llm.py         # LLM backends + OllamaToolAdapter
│   ├── memory.py      # JSONL + TF-IDF memory
│   ├── prompt.py      # Prompt builder
│   ├── search.py      # Shared TFIDFIndex
│   ├── sessions.py    # Session persistence
│   ├── skills.py      # Skill loader + plugin integration
│   ├── server.py      # FastAPI + SSE server + web UI + file upload
│   ├── text_tool_parser.py  # Stateful incremental parser for text-format tool calls
│   ├── plugins/       # Drop-in tool extension directory
│   └── tools/         # decorator.py, builtin.py, registry.py, error_handling.py
├── tests/             # 13 test files, 262 tests
├── micron.yaml        # Provider config
└── pyproject.toml
```

---

## Live work

### Slices 25–27 — CLI / Web App Alignment

**Goal:** Bring the two access modes (CLI and FastAPI web app) to feature
parity. Today the CLI is the richer path; the web app lags on operational
features, and each has capabilities the other lacks.

**Current gaps:**

| Capability | CLI | Web/Server |
|---|---|---|
| Clear history | `/clear` | ❌ |
| Model / provider info | `/model`, `/providers` | ❌ (only bool in `/health`) |
| Unload model | `/unload` | ❌ |
| Sessions list / resume | `/sessions`, `/resume` | ❌ |
| Last response | `/last` | ❌ |
| File recovery | `/trash` `/restore` `/purge` `/undo` | ❌ |
| Directory tree | `/tree` | ❌ |
| Procedure skills | `/skill`, `/skills` | ❌ |
| File upload | ❌ (uses `paste_file`) | `POST /upload` ✅ |
| Delete individual memory | ❌ | `DELETE /memory/{id}` ✅ |
| Write-confirmation UI | inline | Confirm/Cancel buttons ✅ |
| Session persistence | ✅ logged to `context/sessions/` | ❌ (JS-only history) |

**Planned slices:**

- **Slice 25 — Server session endpoints:** add `/sessions`, `/session/{id}`,
  `/session/{id}/resume`; persist web chat to `context/sessions/` via the
  existing `SessionLogger`.
- **Slice 26 — Server operational endpoints:** add `POST /clear`, `GET /model`,
  `GET /providers`, `POST /unload`, and file-recovery `/trash` `/restore`
  `/purge` `/undo`; wire into the web UI.
- **Slice 27 — CLI missing features + docs:** add `--upload` flag and
  per-memory delete to CLI; update README/PLAN.

Sequence note: alignment touches `server.py`, `__main__.py`, and tool
registration — fold into the architecture-review candidates below where
the same files come up.

### Architecture review candidates (2026-08-08)

A 5-candidate architecture review (`/tmp/architecture-review-20260808T203957Z.html`)
identified four deferred deepening opportunities. **Candidate #1
(TextToolCallParser) shipped as part of the same session** (see Recently
shipped). The remaining four are listed below in priority order; see the
report for full diagrams, trade-offs, and ADR callouts.

| # | Candidate | Files | Strength |
|---|---|---|---|
| 2 | **Move the web UI inline markup behind a seam.** The 250 lines of inline HTML+JS+CSS in `server.py`'s `HTML_PAGE` are a second, divergent copy of the event handler that `process_events` already implements. Either delete `micron/static/` (which is dead code) or remove `HTML_PAGE`, serve the static dir, and put the SSE consumer behind an `EventRenderer` interface. | `micron/server.py`, `micron/static/*` | Strong |
| 3 | **Replace the `handle_command` if/elif ladder with a slash-command registry.** New recovery / file tools currently require editing both `builtin.py` and `__main__.py` and adding the name to the hand-maintained `known_commands` set. A `SlashCommandRegistry` with one interface `register(name, run, help)` deepens the CLI without inflating the tool surface. | `micron/__main__.py`, `micron/tools/builtin.py` | Worth exploring |
| ~~4~~ | ~~Share the streaming tool-call parser across LLM backends~~ — shipped [#11](https://github.com/msbuk1/micron-agent/issues/11). | | |
| ~~5~~ | ~~Extract the `run_command` security policy~~ — shipped [#12](https://github.com/msbuk1/micron-agent/issues/12). | | |

The full report (with before/after diagrams, dependency analysis, and
strength justifications) is at `/tmp/architecture-review-20260808T203957Z.html`
on the machine that ran the review. Re-run `/improve-codebase-architecture`
to regenerate it after the live items above land.

---

## Recently shipped

- **CommandPolicy** (architecture #5, [#12](https://github.com/msbuk1/micron-agent/issues/12)) — security checks extracted to `micron/tools/command_policy.py`. `run_command` body shrinks to ~35 LOC. 30 new policy tests.
- **Streaming parser shared across LLM backends** (architecture #4, [#11](https://github.com/msbuk1/micron-agent/issues/11)) — `parse_streaming_tool_calls` extracted to `micron/llm.py`. All three backends call it. 16 new parser tests.
- **TextToolCallParser** (Slice 28 / architecture #1) — stateful SAX-style
  parser owns the streaming buffer the agent used to manage. [ADR 0001](docs/adr/0001-text-tool-call-parser.md).
  31 new tests. `agent.py`: 582 → 484 lines. Patterns shared with the CLI's
  `_strip_thinking` so the two cannot drift.
- **Skills/Tools split** (Slices 19–24) — all 24 tools now exposed to the
  LLM from code via a shared `@tool` decorator; markdown skill files
  no longer gate tool existence. `micron/tools/TOOLS` dict and 16 dead
  `.md` tool-def files deleted.
- **Slices 9–18** (security, tests, tools) — `shell=True` replaced with
  `shlex.split()` + `shell=False`; 30+ command-injection patterns blocked;
  `delete_file` trash recovery; `edit_file` `.bak` undo; `paste_file`,
  `patch_file`, `tree` tools added; TF-IDF consolidated into `micron/search.py`.

---

## Configuration

`micron.yaml` + `MICRON_*` env vars via `Config` (in `micron/config.py`).
CLI uses a second parallel loader (`__main__.load_config`) pre-dating
`Config` — the split is a known seam, out of scope for current work.
See `CONTEXT.md` for the full configuration surface.

---

## Verification

```bash
# All tests
.venv/bin/python -m pytest tests/ -v        # 262 tests

# Architecture review (regenerates the HTML report)
# (run the /improve-codebase-architecture skill)
```

---

## Decisions

Architectural decisions are in [`docs/adr/`](docs/adr/) (Nygard format).
The index lives in [`CONTEXT.md`](CONTEXT.md) under "Architectural
decisions". Read the relevant ADR before refactoring any module it
covers — the decisions are load-bearing.
