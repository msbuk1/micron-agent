# 08 — Fix Test Counts in Docs + Memory Refactor

**What to build:** Update PLAN.md and SLICE_PLAN.md test counts to match actual passing tests. Refactor `Memory._score()` to use `TFIDFIndex` as sole document store, eliminating the redundant `_docs` list.

**Blocked by:** 02 (server test rewrite) and 03 (paste_file fix) — counts depend on final test state.

**Status:** ✅ done — verified in code (2026-08-03)

- [x] PLAN.md test count matches `pytest --co -q` output (168)
- [x] SLICE_PLAN.md test count matches `pytest --co -q` output (168)
- [x] `Memory._score()` uses `self._index.score()` (shared TFIDFIndex)
- [x] `Memory._docs` removed — `TFIDFIndex` is now the sole document store (`add(id, text, doc=entry)`, `get_doc`/`docs` accessors); all Memory methods derive entries from the index. Added tests for `get_doc`/`docs`.
- [x] All memory tests pass
