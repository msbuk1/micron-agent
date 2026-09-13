# Spec: Harness lessons (deepseek-harness → micron)

**Date:** 2026-09-13
**Origin:** deepseek-harness architecture review (everything-is-a-plugin on Cordis) vs micron's Python loop
**Status:** Tickets published
**Tracker:** GitHub issues on `msbuk1/micron-agent` (label `ready-for-agent`) + local mirror under `issues/`

---

## Problem statement

deepseek-harness separates durable session facts from live interception points,
names turns vs steps explicitly, and puts every capability behind a
definition/provider/consumer seam. micron has the same concepts implicitly
(history list, max_tool_iterations loop, global ToolRegistry, WorkspaceFS +
run_command split, three entry points) but without the seams — so policy,
sandboxing, scoping, and replay each require touching the loop.

This batch ports the 6 highest-leverage ideas at micron size. No Cordis, no
plugin tree, no HMR — just documented extension points on the existing
modules.

## Ticket breakdown

Numbered `01`–`06` in dependency order (blockers first). On GitHub they
reference each other by issue number.

| Ticket # | GitHub # | Title | Blocked by |
|---|---|---|---|
| 01 | #15 | Waterfall tool pipeline (pre/post-execute with next/short-circuit) | None |
| 02 | #17 | Turn/Step lifecycle + inbox with inject and turn-stopping | #15 |
| 03 | #20 | Session log as source of truth (deriveMessages + attempt vs message) | #17 |
| 04 | #18 | Scoped tools per agent (isolated registry view) | #15 |
| 05 | #19 | Unified execution seam (fs + subprocess share one world) | #15 |
| 06 | #16 | Profiles as composition + --dump-config | None |

## Frontier (workable in parallel without waiting)

- **01** (#15) — waterfall pipeline
- **06** (#16) — profiles composition

02, 04, 05 all unblock once 01 lands; 03 unblocks once 02 lands.

## Architectural decisions that apply

- ADR 0001 (TextToolCallParser) — pipeline work must not reintroduce regex in the agent loop.
- ADR 0002 (WorkspaceFS) — ticket 05 unifies behind the seam but keeps the containment/verify/trash lifecycle.
- ADR 0003 (MicronAgent seam) — tickets 01–03 extend the loop's extension points; changing the loop updates the turn map in the same PR.
- ADR 0005 (RuntimeConfig gate) — ticket 06 composes RuntimeConfig/ServerRuntime; no parallel loader.
- ADR 0006 (ErrorFormat) — pipeline denial/error rendering goes through the single error seam.

## Domain vocabulary

From `CONTEXT.md`:
`MicronAgent`, `ToolRegistry`, `ToolDescriptor`, `@tool`, `SessionLogger`,
`process_events`, `EventType`, `PromptBuilder`, `KnowledgeIndex`,
`WorkspaceFS`, `CommandPolicy`, `RuntimeConfig`, `ServerRuntime`,
`RateLimiter` / `AuthPolicy`, `ErrorFormat`, `SlashCommandRegistry`.

## Out of scope

- Cordis plugin tree / HMR / Electron host — overkill for local-first Python.
- Multi-modal support, session export, per-provider rate limiting.
- Renaming `MicronAgent` or the event vocabulary.
