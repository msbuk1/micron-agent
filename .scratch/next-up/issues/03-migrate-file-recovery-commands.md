# 4 — Migrate file-recovery + tree commands

**GitHub:** https://github.com/msbuk1/micron-agent/issues/4
**Labels:** `enhancement`, `ready-for-agent`

## What to build

Migrate the file-recovery and tree commands to the new `SlashCommandRegistry`: `/trash`, `/restore`, `/purge`, `/undo`, `/tree`. The old if/elif ladder remains for the aliases only.

## Blocked by

#3 — needs the second batch of registrations complete.

## Acceptance criteria

- [ ] All 5 commands (`/trash`, `/restore`, `/purge`, `/undo`, `/tree`) are registered and dispatched via the registry
- [ ] Old if/elif handles only the help/quit aliases
- [ ] All existing tests pass
