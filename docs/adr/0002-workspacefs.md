# ADR 0002 — WorkspaceFS deep module

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** codebase review (design-it-twice)
- **Origin:** P0 candidate from `CONTEXT.md` deepening review — `micron/tools/builtin.py:1` 1381 LOC, 24 shallow `@tool` adapters

## Context

`micron/tools/builtin.py` held 24 `@tool`-decorated functions each thinly wrapping `os`/`pathlib`/`shutil`. Duplicated policy was scattered:

- `_resolve_path:45` (lexical join + `resolve()` + `is_relative_to` + symlink escape), `_get_workdir:27` env cache, `_verify_write:78` re-read, `_get_trash_dir:68`, `.trash/<name>.<timestamp>` moves, `*.bak` backup lifecycle, truncation/range for `read_file`, binary detection, `tree` depth.

Callers of `read_file`/`write_file`/`edit_file`/`delete_file` etc. each re-implemented or copied one of those helpers. Fixing containment required patching 11 sites; fixing `.trash` naming required 3. Tests for `delete_file`+`restore_file`+`list_trash`+`edit_file`+`undo_file` each set `MICRON_WORKDIR` and asserted timestamp formatting separately — no single place to prove the invariant.

`TFIDFIndex`, `CommandPolicy`, `TextToolCallParser` already showed the deep-module shape: small interface, large hidden policy, `Path` injection in tests.

## Decision

Extract `micron/workspace.py:1` `WorkspaceFS` as single owner of filesystem policy:

```python
class WorkspaceFS:
    def __init__(self, root: Path|str|None=None): ...  # None→MICRON_WORKDIR→Config.workdir→cwd, frozen
    def read(self, path, *, offset, limit, max_bytes=500_000) -> str: ...
    def write(self, path, content, *, create_dirs=True, mode="w", verify=True) -> Path: ...
    def edit(self, path, old, new) -> int: ...
    def patch(self, path, patches) -> int: ...
    def delete(self, path) -> TrashEntry: ...
    def trash(self) -> list[TrashEntry]: ...
    def restore(self, name, *, dest=None) -> Path: ...
    def undo(self, path) -> Path: ...
    def list(self, path=".") -> list[DirEntry]: ...
    def tree(self, path, *, max_depth=3, show_files=True, ext=None) -> str: ...
```

Internal seam: `_resolve(path)->Path` (single containment), `_verify(path, expected)`, `_backup`, `_move_to_trash`. No external `FileSystem` port — variation is *which directory*, a constructor `Path` arg (local-substitutable via `tmp_path`, like `Memory`).

`micron/tools/builtin.py:68` adapters become ~5-line `try: _ws().op() except WorkspaceError→string` translators. `_get_trash_dir`/`TIMESTAMP_FMT` stay as compat shims. LLM tool names/schemas unchanged.

Rejected: (A) 2-verb `read(opts:ReadOpts)/write(opts:WriteOpts)` with `kind="file|dir|tree|trash"` enum — stringly-typed, less discoverable; (B) 18-method flex facet with `ReadOptions/BinaryPolicy/TruncationPolicy` + `ContentDecoder` port — one adapter (PDF) not worth the policy explosion. Chose ergonomic C (common-case `read`/`write` one-liners, progressive `offset/limit/tree`).

## Consequences

### Positive

- **Locality** — containment, verify, trash/.bak in one file; fix once, fixed for 11 adapters.
- **Leverage** — `WorkspaceFS(tmp_path).write/read` exercises containment+atomic tmp+rename+verify for free.
- **Testability** — 47 `test_tools.py` still green; new direct `WorkspaceFS(tmp_path)` tests cover traversal, trash, undo without `MICRON_WORKDIR` env hack beyond singleton.

### Negative

- Singleton `_ws()` in `builtin.py` still snapshots `MICRON_WORKDIR` — env change invalidates; documented.
- `tree()->str` vs `list()->list[DirEntry]` asymmetry intentional (LLM wants string); not unified.
- PDF extraction stays in `WorkspaceFS._read_pdf` via `pymupdf` — binary file handling now hides behind same seam (acceptable).
