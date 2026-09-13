# ADR 0008 — Waterfall tool pipeline (pre/post-execute listeners)

## Status

Accepted

## Context

Tool execution in `ToolRegistry.call` was a direct function invocation.
Cross-cutting concerns (e.g. the `CommandPolicy` blocklist for
`run_command`) were enforced inside individual tool bodies, so there was
no single place to observe, annotate, or deny a tool call, and each tool
re-implemented its own guards.

## Decision

Every `ToolRegistry.call` flows through a waterfall listener chain
(`micron/tools/pipeline.py`):

```
pre-execute -> execute -> post-execute
```

- `ToolListener.pre_execute(invocation, next)` — call `next()` to
  delegate to the rest of the chain (and eventually the tool); return
  without calling `next()` to short-circuit (deny/approve — the tool
  never runs, the returned value is rendered as `tool_error` via
  `ErrorFormat`).
- `ToolListener.post_execute(invocation, result, next)` — call
  `next(result)` to delegate; return without it to replace/annotate the
  result.
- First listener added is outermost. `ToolRegistry.add_listener` /
  `ToolRegistry.listeners` are the seam.
- The pipeline emits `tool_pre` / `tool_post` / `tool_error` events via
  an `_emit` callback; the agent forwards them into its event stream so
  `process_events` consumers and the TUI ToolPanel see them.
- `CommandPolicy` denial for `run_command` routes through a
  `CommandPolicyListener` at pre-execute. The parse+evaluate logic lives
  once in `command_policy.evaluate_command`, shared by the listener and
  `run_command` (which keeps its check as defense-in-depth for direct
  `registry.call` use). No second blocklist.

## Consequences

- New policies (rate limits, audit logging, tool allowlists) are a
  listener, not a change to every tool body.
- Short-circuits are visible as ordinary `tool_error` events — no new
  rendering path in CLI/TUI/web.
- Listener exceptions from `execute` still propagate to the agent's
  existing exception handling; post-execute does not run on failure.
