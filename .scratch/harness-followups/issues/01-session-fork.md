# 01 — Session fork from log projection

**GitHub:** https://github.com/msbuk1/micron-agent/issues/21
**Labels:** `ready-for-agent`

## What to build

Fork a session into a child session seeded purely from the parent log projection. Forking picks a turn boundary in the parent, creates a new session id with a parent link, and the child derives the same history prefix — the parent log is never modified. Settled messages carry over; log-only attempts stay behind (never model-visible in the child). Demo: fork a session with a failed attempt in it and show the child replays the conversation without the failure.

Explicitly deferred from the session-truth ticket; resume/replay already read from the same projection.

## Blocked by

None — can start immediately.

## Acceptance criteria

- [ ] Fork reads parent via the log projection only (no side-channel history)
- [ ] Child derives the parent history prefix up to the chosen boundary; parent untouched
- [ ] Attempts excluded from the child model history but still replayable from the parent
- [ ] Tests cover fork at a boundary, parent immutability, and attempt exclusion
