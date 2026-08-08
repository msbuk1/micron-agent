# 2 — SlashCommandRegistry skeleton + read-only batch

**GitHub:** https://github.com/msbuk1/micron-agent/issues/2
**Labels:** `enhancement`, `ready-for-agent`

## What to build

Add a `SlashCommandRegistry` class (in `__main__.py` or a new module) with one interface: `register(name, run, help) -> SlashCommand` and `dispatch(query) -> None`. Migrate the first batch of read-only commands (`/help`, `/clear`, `/mem`, `/tools`, `/model`, `/providers`) to the registry. The old if/elif ladder stays in place for the unmigrated commands. This is the **expand step** of an expand–contract wide refactor.

The current if/elif ladder in `__main__.py:301-489` is shallow: 17 branches, hand-maintained `known_commands` set, ad-hoc imports of `micron.tools.builtin` for the recovery commands. New tools require editing two files plus the set.

## Blocked by

None — can start immediately.

## Acceptance criteria

- [ ] `SlashCommandRegistry` exists with `register` and `dispatch`
- [ ] `/help`, `/clear`, `/mem`, `/tools`, `/model`, `/providers` are registered and dispatched via the registry
- [ ] Old if/elif still handles the rest; no command is broken
- [ ] All existing tests pass
