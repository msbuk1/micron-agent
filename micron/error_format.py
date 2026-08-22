"""ErrorFormat — deep module hiding friendly copy.

Single table owns isinstance + substring precedence + prefix + truncation.
Both builtin adapters (11 tools) and MicronAgent loop delegate here.
Pure computation, no I/O.
"""
from __future__ import annotations


_MAX_DETAIL = 80
_MAX_FALLBACK = 120


def format_error(exc: BaseException | str, hint: str = "", *, tool: str = "") -> str:
    """Return 'Error: <friendly>' for any exception or string."""
    msg = str(exc) if not isinstance(exc, str) else exc
    lower = msg.lower()
    etype = type(exc).__name__ if not isinstance(exc, str) else ""

    if etype == "FileNotFoundError" or "filenotfounderror" in etype.lower() or "file not found" in lower:
        detail = hint or "the specified file does not exist"
        return f"Error: File not found - {detail}"
    if etype == "PermissionError" or "permission" in lower:
        detail = hint or "you do not have permission to perform this operation"
        return f"Error: Permission denied - {detail}"
    if etype == "TimeoutError" or "timeout" in etype.lower() or "timeout" in lower:
        # covers TimeoutError + any timeout substring (agent + builtin)
        detail = hint or "the operation took too long"
        # agent's friendly uses slightly different wording but we unify;
        # keep timeout path distinct for 3-strike detection
        if "request timed out" in lower or "timed out" in lower:
            return f"Error: Request timed out. Try again later."
        return f"Error: Operation timed out - {detail}"
    if "connection" in lower:
        return f"Error: Connection error. The service may be down or unreachable."
    if "not found" in lower:
        return f"Error: Not found: {msg[:_MAX_DETAIL]}"
    if "invalid" in lower or "bad" in lower:
        detail = hint or msg[:_MAX_DETAIL]
        # builtin prefixes Invalid input with hint; agent prefixes Invalid input with truncated msg
        if hint:
            return f"Error: Invalid input - {hint}"
        return f"Error: Invalid input: {msg[:_MAX_DETAIL]}"
    # WorkspaceFS typed errors duck-typed to avoid import cycle
    if etype in ("OutsideWorkspaceError", "TrashMiss", "VerificationFailed", "WorkspaceError"):
        return f"Error: {msg[:_MAX_FALLBACK]}"
    # generic
    if hint:
        msg = f"{hint}: {msg}"
    if tool:
        return f"Error: {tool} failed: {msg[:_MAX_FALLBACK]}"
    return f"Error: {msg[:_MAX_FALLBACK] if msg else 'Unknown error'}"


def ok(msg: str) -> str:
    return f"Success: {msg}"


def is_error(result: str) -> bool:
    return isinstance(result, str) and result.startswith("Error:")


# compat alias
format_success = ok
