# 08 — Fix Test Counts in Docs + Memory Refactor

**What to build:** Update PLAN.md and SLICE_PLAN.md test counts to match actual passing tests. Refactor `Memory._score()` to use `TFIDFIndex` as sole document store, eliminating the redundant `_docs` list.

**Blocked by:** 02 (server test rewrite) and 03 (paste_file fix) — counts depend on final test state.

**Status:** ⚠️ partial — doc counts done; `Memory._docs` redundancy remains (2026-08-03)

- [x] PLAN.md test count matches `pytest --co -q` output
- [x] SLICE_PLAN.md test count matches `pytest --co -q` output
- [x] `Memory._score()` uses `self._index.score()` (shared TFIDFIndex)
- [ ] `Memory._docs` list still maintained in parallel with the index — not yet made the sole document store; `_docs` still assigned in `_rebuild_index()` and used in list/get/delete. Remaining cleanup (small, independent of tool refactor).
- [x] All memory tests pass
