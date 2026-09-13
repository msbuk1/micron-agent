# 08 — Remove legacy side-channel history path (finish #20/#25)

**GitHub:** https://github.com/msbuk1/micron-agent/issues/28
**Labels:** `ready-for-agent`

## What to build

The agent has exactly one history path. Today it still supports both the side-channel history list (plus _HistoryCompactor) and the session-log authority — all transports run on the truth path since #25, so the legacy path is dead weight. Collapse to one path: log-backed history when a session logger is present, transient in-memory history when sessions are disabled (headless). Delete _HistoryCompactor, the history-param plumbing in the run path, and the now-writerless log_turn method. Keep the turn-entry READ migration (v1 files still need forward-only reads); only the write side goes.

Demo: one-shot, headless, resume, and fork all behave identically with half the history code gone.

## Blocked by

None — can start immediately (though letting the truth path bake a little longer before deleting the fallback is reasonable).

## Acceptance criteria

- [ ] No side-channel history param influences model requests; single history path in the loop
- [ ] _HistoryCompactor and legacy write helpers deleted; zero references
- [ ] Turn-entry read migration for v1 files still works (covered by existing migration test)
- [ ] Full suite green; one-shot, headless-no-session, resume, and fork verified
