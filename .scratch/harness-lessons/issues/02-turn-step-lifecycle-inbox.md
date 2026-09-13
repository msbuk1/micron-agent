# 02 — Turn/Step lifecycle + inbox with inject and turn-stopping

**GitHub:** https://github.com/msbuk1/micron-agent/issues/17
**Labels:** `ready-for-agent`

## What to build

The agent loop distinguishes a step (one model request plus the tools it calls) from a turn (zero or more steps, with explicit turn/start and turn/end). Input reaches the driver through one inbox; some messages wake it immediately while injected context waits until another message does. A pre-step hook can rewrite or reject claimed input (rejected/empty first claim closes the turn with no step) and a turn-stopping hook can end a turn early. Demo: inject context mid-turn, watch it land in the next admitted request, and stop a runaway turn via turn-stopping.

Port of the deepseek-harness turn-flow idea. Builds on the waterfall pipeline ticket; changing the loop updates the documented turn map in the same PR.

## Blocked by

- 01 — Waterfall tool pipeline (#15). Needs the settled tool pipeline to close steps correctly.

## Acceptance criteria

- [ ] Turn opens before first input is claimed and closes once nothing is owed; steps are logged with start/end
- [ ] agent.inject() lands in the next admitted request, never mid-stream
- [ ] pre-step rewrite/reject and turn-stopping interception both work and are covered by tests
- [ ] CLI, TUI, and server render turn/step boundaries (or deliberately ignore them via one documented seam)
