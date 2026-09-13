# 03 — Web UI parity: pipeline + attempt events

**GitHub:** https://github.com/msbuk1/micron-agent/issues/23
**Labels:** `ready-for-agent`

## What to build

The web UI renders what the agent already emits. The event renderer gains cards for the tool pipeline visibility events (pre/post-execute around each call), and the transcript endpoint exposes log-only attempts (failed/retried/cancelled streams) for replay display — distinct from model-visible messages. Demo: run a task with a denied tool call plus a retried stream in the browser and show both rendered; the existing chat flow is unaffected.

Mirrors the process_events seam the CLI/TUI already consume; unknown event types stay ignored.

## Blocked by

None — can start immediately.

## Acceptance criteria

- [ ] Pre/post-execute events render as tool cards in the web UI
- [ ] Attempts are readable via the transcript path without entering model history
- [ ] Existing chat rendering and streaming behavior unchanged
- [ ] Tests cover the new rendering paths
