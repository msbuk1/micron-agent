# 07 — Rename check_api_key + .bak Auto-Cleanup

**What to build:** Rename `check_api_key()` to `is_valid_api_key()` for clarity. Add auto-cleanup of `.bak` files older than 7 days in `edit_file`.

**Blocked by:** 01 — needs `AuthConfig` dataclass in place.

**Status:** ✅ done — verified in code (2026-08-03)

- [x] `check_api_key` renamed to `is_valid_api_key` everywhere
- [x] `edit_file` deletes `.bak` files older than 7 days before creating new backup
- [x] All tests pass after rename
