# 03 — Session log as source of truth (deriveMessages + attempt vs message)

**GitHub:** https://github.com/msbuk1/micron-agent/issues/20
**Labels:** `ready-for-agent`

## What to build

The append-only session log becomes the source of the context the model sees — model history is projected from it (deriveMessages), never reconstructed from a side-channel history list. Settled assistant output commits as one message; failed/retried/cancelled streams commit as log-only attempts that never enter model history. New model-visible input requires a new session event type. Demo: resume/fork/replay a session purely from its log, including a failed attempt that the model correctly never sees.

Port of the deepseek-harness model-visible-means-logged invariant plus the projection seam. Replaces the destructive HistoryCompactor summary with lossless settlement; SessionLogger becomes the authority, not the audit trail.

## Blocked by

- 02 — Turn/Step lifecycle (#17). Needs turn/step boundaries to settle messages vs attempts correctly.

## Acceptance criteria

- [ ] Model requests are derived from the log; a runtime check asserts model-visible content is reconstructable from it
- [ ] Failed/retried/cancelled attempts persist as attempts (replayable, UI-visible) without polluting model history
- [ ] Resume, fork, and transcript all read from the same log projection
- [ ] Stored sessions carry a format version with a forward-only adjacent-migration step; committed generations are never rewritten in place
