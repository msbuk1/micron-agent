# 07 — ADR 0009: profiles composition

**GitHub:** https://github.com/msbuk1/micron-agent/issues/27
**Labels:** `ready-for-agent`

## What to build

The profiles-composition decision is recorded following the repo ADR convention (Nygard format: Status / Context / Decision / Consequences) with a glossary row, so future reviews don't re-litigate it. Covers named profiles over one boot path, ordered patch layers (base, profile, home, overlay), whole-row replace-or-insert by id with loud failure on unknown rows, and --dump-config as the introspection seam.

Recorded after the presets ticket lands so the ADR describes final semantics including the preset/tools row.

## Blocked by

- 02 — Presets through boot (#22). The ADR must describe final semantics including the preset row.

## Acceptance criteria

- [ ] ADR file accepted in docs/adr/ following Nygard format and repo convention
- [ ] Glossary updated with the decision reference
- [ ] Reflects final composition semantics (post-preset wiring)
