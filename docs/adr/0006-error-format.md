# ADR 0006 — ErrorFormat deep module

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** codebase review (design-it-twice P6)
- **Origin:** remaining shallow — `micron/tools/error_handling.py:1` (`handle_error`/`success`) vs `MicronAgent._friendly_error:374` duplicate friendly copy

## Context

One seam, two implementations. `handle_error(tool, exc, context)` and `_friendly_error(tool, exc)` both mapped `FileNotFoundError`→"not found", `PermissionError`, `TimeoutError`, `"connection"`/`"not found"`/`"invalid"` substring checks, with divergent copy (`"File not found - …"` vs `"File not found. Check the path…"`) and truncation (`[:80]` vs `[:120]`) and prefix (`"Error: "` vs bare). Fixing copy required two patches; 11 builtin adapters + 2 agent catch sites drifted. Tests asserted `"Error:"` prefix via `result.startswith("Error:")` `agent.py:444` — prefix contract was implicit.

`CommandPolicy` and `TextToolCallParser` showed pure in-process tables belong in one module.

## Decision

`micron/error_format.py:1` pure module:

```python
def format_error(exc: BaseException|str, hint: str = "", *, tool: str = "") -> str: ...  # always "Error: …"
def ok(msg: str) -> str: ...  # "Success: …"
def is_error(result: str) -> bool: ...  # result.startswith("Error:")
```

Single ordered table hides `isinstance`→substring precedence, `hint` fallback, `tool` fallback `f"{tool} failed: …"`, `80`/`120` truncation, `WorkspaceError` duck typing to avoid `workspace.py` cycle. `MicronAgent._friendly_error` → `format_error(e, tool=tc.name).removeprefix("Error: ")`. `micron/tools/error_handling.py:1` becomes shim `from micron.error_format import format_error as handle_error` (`success` → `ok`) for plugin compat.

Rejected: (B) `ErrorFormatter` class + `ErrorPayload`/`LocaleProvider`/`register` 12-method flex — one locale adapter not worth seam; (A) single `format_error` without `ok` — loses `Success:` symmetry. Chose ergonomic C: `hint=""` positional #2 + `tool=""` kw-only (dead for 11 builtins, used for agent fallback).

## Consequences

### Positive

- **Locality** — copy, precedence, truncation in one file; fix once.
- **Leverage** — 11 adapters + 2 agent sites collapse to one call shape; `is_error` stabilizes prefix contract.
- **Testability** — synthetic `format_error(FileNotFoundError("x"))` without `tmp_path`.

### Negative

- Frozen `"Error: "`/`"Success: "` contract — `EventRenderer` must `removeprefix` if bare text desired.
- String-pattern heuristic (`"connection" in lower`) stays; structured `WorkspaceError` hierarchy deferred until second typed error family appears.
- Shim file remains one release.
