# Spec: Next-Up — CLI/Web Alignment + Architecture Refactors

**Date:** 2026-08-08
**Origin:** Slimmed `PLAN.md` (post TextToolCallParser ship)
**Status:** Ready for tickets
**Tracker:** GitHub issues on `msbuk1/micron-agent` (label `ready-for-agent`)

---

## Problem statement

Two related workstreams have piled up since the Skills/Tools split shipped:

1. **CLI / Web App feature parity** — the CLI has slash commands and session
   persistence the web app doesn't have, and the web app has file upload
   the CLI doesn't. Slices 25–27 (already documented in `PLAN.md`).

2. **Architecture review findings** — a 5-candidate review on 2026-08-08
   identified 4 deferred code-quality refactors alongside the now-shipped
   TextToolCallParser. Report at
   `/tmp/architecture-review-20260808T203957Z.html`.

Together these form the next batch of work. Each ticket is sized to
fit in a single fresh context window.

## Ticket breakdown

Tickets are numbered `01`–`12` in dependency order (blockers first). On
GitHub they reference each other by issue number. The local mirror under
`issues/` records the GitHub URL for each.

| Ticket # | GitHub # | Title | Blocked by | Workstream |
|---|---|---|---|---|
| 01 | [#2](https://github.com/msbuk1/micron-agent/issues/2) | `SlashCommandRegistry` skeleton + read-only batch | None | Slash command registry (wide refactor — expand) |
| 02 | [#3](https://github.com/msbuk1/micron-agent/issues/3) | Migrate session-management commands | #2 | Slash command registry |
| 03 | [#4](https://github.com/msbuk1/micron-agent/issues/4) | Migrate file-recovery + tree commands | #3 | Slash command registry |
| 04 | [#5](https://github.com/msbuk1/micron-agent/issues/5) | Delete old if/elif ladder (contract) | #4 | Slash command registry |
| 05 | [#6](https://github.com/msbuk1/micron-agent/issues/6) | Server writes to `context/sessions/` during chat | None | Server session work |
| 06 | [#7](https://github.com/msbuk1/micron-agent/issues/7) | Server session endpoints (`/sessions`, `/session/{id}/resume`) | #6 | Server session work |
| 07 | [#8](https://github.com/msbuk1/micron-agent/issues/8) | Server operational endpoints (info: `/clear`, `/model`, `/providers`, `/unload`) | None | Server operational endpoints |
| 08 | [#9](https://github.com/msbuk1/micron-agent/issues/9) | Server file-recovery endpoints (`/trash`, `/restore`, `/purge`, `/undo`) | None | Server operational endpoints |
| 09 | [#10](https://github.com/msbuk1/micron-agent/issues/10) | Web UI seam — serve `micron/static/` | None | Architecture review #2 |
| 10 | [#11](https://github.com/msbuk1/micron-agent/issues/11) | Share streaming tool-call parser across LLM backends | None | Architecture review #4 |
| 11 | [#12](https://github.com/msbuk1/micron-agent/issues/12) | Extract `CommandPolicy` from `run_command` | None | Architecture review #5 |
| 12 | [#13](https://github.com/msbuk1/micron-agent/issues/13) | CLI `--upload` flag and per-memory delete | #5 | CLI missing features |

## Frontier (workable in parallel without waiting)

After ticket creation, the **frontier** — tickets that have no
unresolved blockers — is:

- **01** (no blockers) — slash command registry skeleton
- **05** (no blockers) — server session persistence
- **07** (no blockers) — server info endpoints
- **08** (no blockers) — server file-recovery endpoints
- **09** (no blockers) — web UI seam
- **10** (no blockers) — streaming parser shared
- **11** (no blockers) — `CommandPolicy` extraction

Seven tickets are workable in parallel as soon as they're created. 12
depends on 04 which depends on 01–03.

## Architectural decisions that apply

- **ADR 0001** (TextToolCallParser) — already accepted. Constrains the
  streaming parser work in ticket 10 (don't reintroduce regex in
  `agent.py`).
- No other ADRs gate this batch.

## Domain vocabulary

From `CONTEXT.md`:
`SlashCommandRegistry` (new), `MicronAgent`, `SessionLogger`,
`TextToolCallParser`, `LLMBackend`, `ToolRegistry`, `ToolDescriptor`.

## Out of scope

- Plugin hot-reload (was "Feature Idea" in old PLAN.md — leave for later)
- Multi-modal support (vision)
- Session export
- Rate limiting per-provider
- Multi-modal support
- Renaming `MicronAgent` to anything else
