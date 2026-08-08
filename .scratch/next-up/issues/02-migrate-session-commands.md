# 3 — Migrate session-management commands

**GitHub:** https://github.com/msbuk1/micron-agent/issues/3
**Labels:** `enhancement`, `ready-for-agent`

## What to build

Migrate the session-management commands to the new `SlashCommandRegistry`: `/unload`, `/reload`, `/sessions`, `/resume`, `/last`, `/skill`, `/skills`. The old if/elif ladder remains for the unmigrated file-recovery commands.

## Blocked by

#2 — `SlashCommandRegistry` must exist before migration.

## Acceptance criteria

- [ ] All 7 commands (`/unload`, `/reload`, `/sessions`, `/resume`, `/last`, `/skill`, `/skills`) are registered and dispatched via the registry
- [ ] Old if/elif still handles `/trash`, `/restore`, `/purge`, `/undo`, `/tree`
- [ ] All existing tests pass
