# 06 — Delegate Slash Commands to Tool Functions

**What to build:** Make `/trash`, `/restore`, `/purge`, `/undo` in `__main__.py` call tool functions from `builtin.py` instead of reimplementing path logic. Extract command routing from the main loop.

**Blocked by:** 01 — needs `_get_trash_dir()` and the foundational refactors in place.

**Status:** ✅ done — verified in code (2026-08-03)

- [x] `/trash` calls `list_trash()` from builtin
- [x] `/restore` calls `restore_file()` from builtin
- [x] `/purge` calls a `purge_trash()` tool function instead of inline `shutil.rmtree`
- [x] `/undo` calls `undo_file()` from builtin
- [x] No duplicated path construction between `__main__.py` and `builtin.py`
