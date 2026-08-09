# Plan: Textual TUI for micron

## Status

Implemented. The TUI replaces the old interactive CLI; one-shot mode and the web
UI are unchanged.

## Scope

Replace the plain interactive CLI (`python -m micron -i`) with a full-screen
Textual TUI. One-shot query mode (`python -m micron "query"`) and the web UI
(`python -m micron --server`) remain untouched.

## Decisions

| Topic | Decision |
|---|---|
| Launch | `python -m micron` with no args launches the TUI. `python -m micron -i` also launches the TUI. |
| Old interactive REPL | Removed. |
| Dependency | Add `textual>=0.70`. |
| Layout | Multi-pane: `ChatLog` + `ToolPanel` + `Sidebar` + `InputBar` + `StatusBar`. |
| Mouse + shortcuts | Yes. |
| Web UI | Leave as-is; may be retired later. |
| Model loading | Show a spinner/status while `MicronAgent` initializes. |
| Chat rendering | Assistant messages render as Markdown. |
| Tool output | Summary in `ToolPanel`; full result in a detail popup on `Enter`. |
| Theme | Custom Textual CSS file (`app.tcss`). |
| Menu button | Exposes slash commands, model info, reload skills, unload model, help, quit. |
| Focus | Stays in input; shortcuts navigate (`Ctrl+B` sidebar, `Ctrl+K` input, etc.). |
| Confirmation default | `No` for write-tool modals. |
| Session resume | Pick-list in the sidebar Sessions tab. |
| Worker threading | `MicronTUI` accepts `thread_workers` (default `True`). Tests use `thread_workers=False` to avoid thread-pool exhaustion in the test runner. |

## Files

### Modified

- `pyproject.toml` — add `textual>=0.70` and `pytest-asyncio>=0.23` dependencies.
- `micron/__main__.py` — remove `run_interactive`, add `create_agent_and_logger`, route no-args and `-i` to the TUI, keep one-shot `run_query`.

### New

- `micron/tui/__init__.py` — package marker.
- `micron/tui/app.py` — main `MicronTUI` Textual App class.
- `micron/tui/commands.py` — slash command dispatcher.
- `micron/tui/worker.py` — sync (`run_agent`) and async (`run_agent_async`) agent event workers.
- `micron/tui/widgets/chat.py` — `ChatLog` widget.
- `micron/tui/widgets/tool_panel.py` — `ToolPanel` widget.
- `micron/tui/widgets/sidebar.py` — `Sidebar` widget with tabs.
- `micron/tui/widgets/input_bar.py` — `InputBar` widget.
- `micron/tui/widgets/status_bar.py` — `StatusBar` widget.
- `micron/tui/screens/confirm.py` — `ConfirmationScreen` modal.
- `micron/tui/screens/help.py` — `HelpScreen` modal.
- `micron/tui/app.tcss` — custom theme.
- `tests/test_tui.py` — headless Textual tests.

## Architecture

```
micron/__main__.py
   └─ main()
        ├─ one-shot query → run_query()
        └─ no args / -i  → MicronTUI(factory).run()

MicronTUI
   ├─ ChatLog          ← streaming text, thinking, markdown
   ├─ ToolPanel        ← tool_start / tool_result / tool_error
   ├─ Sidebar          ← tabs: Memories, Knowledge, Skills, Sessions
   ├─ InputBar         ← input + send + menu
   ├─ StatusBar        ← session/model/memory counts
   └─ Worker           ← consumes agent.run(), posts UI messages
```

## Event Flow

1. User submits a message; the agent runs in a Textual `Worker`.
2. Worker yields events and posts Textual messages to the UI thread via
   `app.post_message()` (thread-safe).
3. UI updates `ChatLog`, `ToolPanel`, and `StatusBar`.
4. On `confirmation_required`, push `ConfirmationScreen` (default `No`).
5. On confirm, worker resumes with `confirm=True` and pending tool calls.
6. On `done`, re-enable input.

## Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Q` | Quit |
| `Ctrl+L` | Clear chat history |
| `Ctrl+K` | Focus input |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+/` | Show help |
| `Enter` | Send message (when input is focused) |

## Sidebar Tabs

- **Memories**: list, search, add new.
- **Knowledge**: list, search.
- **Skills**: list, load procedure skill into context.
- **Sessions**: list, resume selected session (pick-list).

## Slash Commands

All existing commands preserved and also reachable via the menu:
`/help`, `/exit`, `/quit`, `/clear`, `/mem`, `/tools`, `/model`, `/providers`,
`/unload`, `/reload`, `/sessions`, `/resume`, `/last`, `/trash`, `/restore`,
`/purge`, `/undo`, `/tree`, `/skill`, `/skills`.

## Testing

- Use Textual’s `app.run_test()` headless driver.
- Tests instantiate `MicronTUI(..., thread_workers=False)` so they run in the
  event loop and avoid exhausting the test runner’s thread pool.
- Coverage: app mounting, input submission, `/clear`, tool event handling,
  confirmation screen default.
- Full suite: `267 passed`.

## Implementation Order (completed)

1. Add `textual` and `pytest-asyncio` dependencies.
2. Create `micron/tui/` package and base CSS.
3. Implement widgets.
4. Implement screens.
5. Implement commands and worker (sync + async variants).
6. Wire `MicronTUI` and update `__main__.py`.
7. Add `tests/test_tui.py`.
8. Run tests and manual smoke test.
