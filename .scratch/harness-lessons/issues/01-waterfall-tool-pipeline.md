# 01 — Waterfall tool pipeline (pre/post-execute with next/short-circuit)

**GitHub:** https://github.com/msbuk1/micron-agent/issues/15
**Labels:** `ready-for-agent`

## What to build

Every tool call flows through an interceptable pipeline (pre-execute -> execute -> post-execute) surfaced via the existing EventType/process_events vocabulary. A policy or sandbox listener can observe, annotate (must delegate via next()), or short-circuit (deny/approve without calling next()) without touching the MicronAgent loop. Demo: a listener denies a dangerous run_command from pre-execute and the denial renders as a tool_error with no subprocess spawned.

Port of the deepseek-harness tools/* waterfall idea, cut down to micron size. No Cordis, no plugin tree — just a documented extension point on ToolRegistry.

## Blocked by

None — can start immediately.

## Acceptance criteria

- [ ] Tool calls emit pre-execute and post-execute around execute, visible to process_events consumers and the TUI ToolPanel
- [ ] Listeners that only observe/annotate delegate; a listener that owns the decision short-circuits (documents next() semantics)
- [ ] Existing CommandPolicy denial path routes through pre-execute (no second blocklist implementation)
- [ ] All existing tests pass; new tests cover observe, annotate-and-delegate, and short-circuit-deny
