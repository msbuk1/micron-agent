# 05 — Transports on the truth path (drop log_turn double-booking)

**GitHub:** https://github.com/msbuk1/micron-agent/issues/25
**Labels:** `ready-for-agent`

## What to build

Every transport (CLI one-shot, TUI, server) runs the agent with the session log as authority instead of the legacy audit-trail path. The server runtime and CLI inject the session logger into the agent at construction, and the transport-side legacy log calls are removed — exactly one logging path, no double-booking. Demo: chat from each transport, then resume the session and show identical, complete history with no duplicate entries.

The truth path is already opt-in at the agent level; this ticket flips the transports over to it.

## Blocked by

None — can start immediately.

## Acceptance criteria

- [ ] All three transports inject the session logger; the log is the authority in each
- [ ] Legacy transport-side log calls removed; no duplicate entries in session files
- [ ] Resume and transcript read correctly for sessions from every transport
- [ ] Tests cover per-transport logging with no duplication
