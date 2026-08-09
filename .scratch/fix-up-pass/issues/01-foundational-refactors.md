# 01 — Foundational Refactors (AuthConfig, _get_trash_dir, timestamp const)

**What to build:** Extract a `_get_trash_dir()` helper to eliminate 3× duplicated trash path construction. Replace `get_authentication()` raw dict return with an `AuthConfig` dataclass. Extract `TIMESTAMP_FMT` constant to replace magic string slicing in `list_trash`.

**Blocked by:** None — can start immediately.

**Status:** ✅ done — verified in code (2026-08-03)

- [x] `_get_trash_dir()` helper exists and is used by `delete_file`, `restore_file`, `list_trash`
- [x] `get_authentication()` returns `AuthConfig` dataclass with `enabled`, `api_key_required`, `api_key_env_var` fields
- [x] `list_trash` uses named constant for timestamp format instead of `len(parts[1]) == 15`
- [x] All existing tests still pass
