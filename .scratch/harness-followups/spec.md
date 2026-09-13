# Spec: Harness follow-ups (leftovers from #15–#20 + loop plan)

**Date:** 2026-09-13
**Origin:** Worker follow-ups from the harness-lessons batch (#15–#20, all shipped) plus completed loop-improvements plan
**Status:** Tickets published
**Tracker:** GitHub issues on `msbuk1/micron-agent` (label `ready-for-agent`) + local mirror under `issues/`

---

## Problem statement

The harness-lessons batch and the agent-loop plan are fully shipped (467 tests green, all issues closed). The implementation workers left behind seven small, well-understood leftovers: one deferred feature (fork), three wiring jobs (presets, transports, web parity), two cleanups (shim removal, test hygiene), and one docs decision (ADR 0009).

## Ticket breakdown

Numbered `01`–`07` in dependency order (blockers first). On GitHub they reference each other by issue number.

| Ticket # | GitHub # | Title | Blocked by |
|---|---|---|---|
| 01 | #21 | Session fork from log projection | None |
| 02 | #22 | Presets through boot + --preset flag | None |
| 03 | #23 | Web UI parity: pipeline + attempt events | None |
| 04 | #24 | Test hygiene: tmp_path isolation | None |
| 05 | #25 | Transports on the truth path | None |
| 06 | #26 | Remove ServerRuntime.load() shim | None |
| 07 | #27 | ADR 0009: profiles composition | #22 |

## Frontier (workable in parallel without waiting)

- **01** (#21), **02** (#22), **03** (#23), **04** (#24), **05** (#25), **06** (#26) — all six start immediately.
- **07** (#27) unblocks once 02 lands.

## Architectural decisions that apply

- ADR 0008 (tool pipeline) — ticket 03 renders its events; no pipeline changes.
- ADR 0002 (WorkspaceFS) — untouched by this batch.
- Session truth (#20) — tickets 01 and 05 build on derive_messages; don't rework it.

## Domain vocabulary

From `CONTEXT.md`:
`MicronAgent`, `SessionLogger`, `derive_messages`, `ScopedToolRegistry`,
`AgentPreset`, `compose_tools`, `ServerRuntime`, `RuntimeConfig`,
`process_events`, `EventType`, `ErrorFormat`.

## Out of scope

- New agent capabilities or tools — wiring and cleanup only.
- LLM-based summarization, parallel tools, event bus (already rejected).
