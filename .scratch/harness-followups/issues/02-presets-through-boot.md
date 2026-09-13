# 02 — Presets through boot + --preset flag

**GitHub:** https://github.com/msbuk1/micron-agent/issues/22
**Labels:** `ready-for-agent`

## What to build

Agent presets stop being a construction-time-only helper and become a first-class boot input. The boot composition carries a tools/preset row, the server runtime honors it, and the CLI exposes a --preset flag — so running with the plan preset (read/search only) works from every entry point while the default preset keeps the full toolset. The resolved preset shows up in --dump-config. Demo: run a one-shot task under --preset plan and show the model only ever sees the reduced schemas.

Builds on the scoped-tools view and the profiles composition; no new scoping mechanism.

## Blocked by

None — can start immediately.

## Acceptance criteria

- [ ] Boot accepts a preset name; unknown names fail loudly
- [ ] CLI --preset flag works for one-shot, TUI, and server paths
- [ ] --dump-config shows the resolved preset and effective toolset
- [ ] Default behavior unchanged; tests cover default, plan preset, and unknown preset
