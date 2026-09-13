# 04 — Test hygiene: tmp_path isolation, no repo-root stray files

**GitHub:** https://github.com/msbuk1/micron-agent/issues/24
**Labels:** `ready-for-agent`

## What to build

Running the full test suite leaves the working tree clean. The tests that currently drop stray files into the repo root (confirmed.txt, out.txt and friends) are moved to per-test tmp_path isolation, so git status shows nothing after a green run. Demo: run the suite twice in a row and show git status clean both times with all tests passing.

No behavior change — pure test hygiene.

## Blocked by

None — can start immediately.

## Acceptance criteria

- [ ] Full suite passes with zero new untracked/modified files in the repo
- [ ] Affected tests use tmp_path (or equivalent isolation) for all file writes
- [ ] Suite stays green; no production code changes required (or minimal, if a default path needs overriding in tests)
