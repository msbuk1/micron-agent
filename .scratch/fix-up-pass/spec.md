# Spec: Fix-Up Pass — Code Review Findings

**Date:** 2026-07-24
**Origin:** Code review of `e8639b6...HEAD` (slices 9–18)
**Status:** Ready for tickets

---

## Problem Statement

The code review of slices 9–18 found 8 spec gaps (requirements the slice specs asked for that weren't implemented) and 7 code smells (duplicated logic, inconsistent path construction, primitive obsession). These issues compound: the trash path bug is a latent correctness problem, the inflated test count masks skipped tests, and missing skill definitions mean the agent can't discover new tools.

## Solution

A focused fix-up pass that closes every gap the review identified, organized into two workstreams:

1. **Spec failures** — complete the requirements slices 9–18 left unfinished
2. **Standards fixes** — eliminate the duplicated/inconsistent code the review flagged

## User Stories

### Spec failures

1. As a developer, I want server tests rewritten with `httpx.AsyncClient` instead of skipped, so that test counts are honest and the server is actually tested
2. As a developer, I want `paste_file(content, filename=None)` with auto-generated filenames saved to `context/uploads/`, so that the tool matches its spec and can be used for quick content upload
3. As an agent, I want `context/skills/paste_file.md` to exist, so that I can discover the paste_file tool through the skill system
4. As an agent, I want `context/skills/patch_file.md` to exist, so that I can discover the patch_file tool through the skill system
5. As a user, I want a `/tree` slash command in interactive mode, so that I can visualize the directory structure without using the tool directly
6. As a user, I want `tree` to support `--ext=py` filtering, so that I can see only files of a specific type
7. As a developer, I want test counts in PLAN.md and SLICE_PLAN.md to reflect actual passing tests (not skipped), so that the metrics are trustworthy
8. As a developer, I want `.bak` auto-cleanup for files older than 7 days, so that backup files don't accumulate indefinitely

### Standards fixes

9. As a developer, I want a single `_get_trash_dir()` helper, so that trash path construction isn't duplicated across 3 functions
10. As a developer, I want `/purge` to use the same path logic as `builtin.py`, so that the two implementations can't diverge
11. As a developer, I want the trash/restore/undo slash commands to delegate to tool functions rather than reimplementing path logic, so that changes to trash behavior only need one code path
12. As a developer, I want the `YYYYMMDD_HHMMSS` timestamp format extracted to a constant or helper, so that `list_trash` doesn't rely on magic string slicing
13. As a developer, I want `get_authentication()` to return a dataclass instead of a raw dict, so that callers don't index by magic strings
14. As a developer, I want `check_api_key` renamed to `is_valid_api_key`, so that the name reflects its boolean return
15. As a developer, I want `Memory._score()` to avoid redundant parallel data structures with `TFIDFIndex`, so that the index is the single source of truth for document storage
16. As a developer, I want `__main__.py` command routing extracted to a command registry, so that new slash commands don't grow the main loop

## Implementation Decisions

### Modules to modify

- `micron/tools/builtin.py` — add `_get_trash_dir()`, refactor trash/restore/undo to use it, fix `paste_file` signature to match spec, add `tree` ext filter
- `micron/__main__.py` — add `/tree` slash command, extract command routing to a registry, make `/purge` delegate to a tool function
- `micron/config.py` — replace `get_authentication()` dict return with a `@dataclass AuthConfig`, rename `check_api_key` → `is_valid_api_key`
- `micron/memory.py` — remove redundant `_docs` list, use `TFIDFIndex` as sole document store
- `tests/test_server.py` — rewrite with `httpx.AsyncClient` instead of threading skip
- `tests/test_tools.py` — update `paste_file` tests for new signature
- `PLAN.md` — fix test counts to reflect actual passing tests
- `SLICE_PLAN.md` — fix test counts

### New files

- `context/skills/paste_file.md` — skill definition for paste_file tool
- `context/skills/patch_file.md` — skill definition for patch_file tool

### Interfaces

- `paste_file(content: str, filename: str = None) -> str` — content-first, optional filename, saves to `context/uploads/`
- `tree(path: str, max_depth: int = 3, show_files: bool = True, ext: str = None) -> str` — added `ext` parameter
- `get_authentication() -> AuthConfig` — returns dataclass instead of dict
- `is_valid_api_key(provided_key: str = None) -> bool` — renamed from `check_api_key`

### Architectural decisions

- Command routing in `__main__.py` should be a dict mapping command names to handler functions, not an if/elif chain
- The trash directory path should be computed once from `_get_workdir()` and shared across all trash operations
- `/purge` should become a tool function (e.g. `purge_trash()`) called by the slash command, not inline logic

## Testing Decisions

- Server tests: rewrite with `httpx.AsyncClient` and async fixtures; if threading still fails in sandbox, use `pytest.mark.skipif` with a clear reason string (not silent skip)
- Paste file tests: update for new `paste_file(content, filename=None)` signature
- All existing tests must continue to pass
- Test counts in docs must match `pytest --co -q` output exactly

## Out of Scope

- Refactoring `__main__.py` into a full command registry pattern (just extract the trash/undo handlers)
- Adding new tools or features beyond what the review found
- Changing the TF-IDF scoring algorithm
- Modifying the web UI

## Further Notes

- The `.bak` auto-cleanup is marked optional in the original slice 14 spec. Include it but keep it simple: a helper that runs on `edit_file` and deletes `.bak` files older than 7 days.
- The scope creep finding (`check_api_key` not in spec) is being kept — it's useful. The fix is just renaming it.
