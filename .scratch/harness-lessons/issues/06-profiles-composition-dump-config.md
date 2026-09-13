# 06 — Profiles as composition + --dump-config

**GitHub:** https://github.com/msbuk1/micron-agent/issues/16
**Labels:** `ready-for-agent`

## What to build

CLI, TUI, and server launch as named profiles (same agent + backend + sessions wiring underneath) instead of three separate entry paths. Ordered patch layers apply over the base composition (bundle order, then profile patch, then home patch, then --patch overlay). A --dump-config flag prints the resolved tree so any row can be replaced by a patch of your own. Demo: run a one-shot headless task and the web server from the same composition code, and introspect the boot tree.

Port of the deepseek-harness profiles/bundles idea. RuntimeConfig and ServerRuntime stay; they become the typed viewport the profiles compose — not parallel loaders.

## Blocked by

None — can start immediately.

## Acceptance criteria

- [ ] One boot path composes agent + sessions + limiter/auth for every profile (no drift between CLI/TUI/server wiring)
- [ ] Ordered patch layers apply deterministically; later layers replace whole rows by id or insert new rows
- [ ] --dump-config prints the resolved composition a user can patch against
- [ ] All existing tests pass; new tests cover layer ordering and dump output
