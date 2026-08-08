# 11 — Extract CommandPolicy from run_command

**Status:** ✅ done

**GitHub:** https://github.com/msbuk1/micron-agent/issues/12
**Labels:** `enhancement`, `ready-for-agent`

## What to build

`run_command` in `micron/tools/builtin.py` is 150 LOC that mixes command parsing, blocklist, flag scan, pipe / `$()` blocking, redirect-to-block-device blocking, and resource limits. Extract the inline security checks into a `CommandPolicy.evaluate(args) -> Decision` module. The tool body becomes "parse, evaluate, run, format". New rules are a one-line change.

## Blocked by

None — independent of the other work.

## Acceptance criteria

- [ ] `CommandPolicy` exists with one method `evaluate(args) -> Decision` (Decision has `.allow | .deny(reason) | .limit(rlimits)`)
- [ ] `run_command` body shrinks to ~15 lines: parse cmd, evaluate policy, apply limits, run subprocess, format
- [ ] Policy can be tested with synthetic args — no subprocess needed
- [ ] All existing tests pass
