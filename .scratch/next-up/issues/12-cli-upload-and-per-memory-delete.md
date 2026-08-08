# 13 — CLI --upload flag and per-memory delete

**GitHub:** https://github.com/msbuk1/micron-agent/issues/13
**Labels:** `enhancement`, `ready-for-agent`

## What to build

Two CLI features that mirror web-app capabilities:
1. `python -m micron --upload <path>` — post a file to the server's `/upload` endpoint
2. `/memory delete <id>` — delete a single memory by id (web app already has this via `DELETE /memory/{id}`)

Both use the new `SlashCommandRegistry` (ticket 04) so they don't grow the if/elif ladder.

## Blocked by

#5 — the SlashCommandRegistry refactor must be complete so the new commands register cleanly.

## Acceptance criteria

- [ ] `python -m micron --upload <path>` posts the file and prints the returned path
- [ ] `/memory delete <id>` (in interactive mode) calls the existing `Memory.delete` and confirms
- [ ] Both new commands register via `SlashCommandRegistry`, not via if/elif
- [ ] All existing tests pass
