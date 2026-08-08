# 5 — Delete old if/elif ladder

**GitHub:** https://github.com/msbuk1/micron-agent/issues/5
**Labels:** `enhancement`, `ready-for-agent`

## What to build

**Contract step** of the slash command registry refactor. Remove the if/elif ladder from `__main__.py` and the hand-maintained `known_commands` set. The `SlashCommandRegistry` is the sole source of slash commands. `/help` auto-generates from the registered commands.

## Blocked by

#4 — all commands must be migrated before the old ladder can be deleted.

## Acceptance criteria

- [ ] The if/elif ladder is removed from `__main__.py`
- [ ] `known_commands` set is removed
- [ ] `/help` is generated from the registry
- [ ] All existing tests pass
