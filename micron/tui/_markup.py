"""Markup helpers for micron TUI widgets."""
from __future__ import annotations

import re

# Escape any ``[`` so Textual markup treats it as literal. Tool output,
# file paths, error strings, and shell messages routinely contain ``[``
# followed by all sorts of characters (``(``, digits, ``=``, letters).
# Textual's markup tokenizer is lenient with tag bodies — it extracts
# unmatched characters as text instead of erroring — which means a stray
# ``[`` followed by ``letter=...`` can silently flip the parser into
# ``expect_markup_expression`` state and raise ``MarkupError`` on the next
# ``=``. The robust fix is to escape every ``[`` we don't own.
_BRACKET_RE = re.compile(r"\[(?=[^\[])")


def esc(text: str) -> str:
    """Escape every ``[`` so Textual markup treats it as literal text."""
    if not text:
        return text
    return _BRACKET_RE.sub("\\[", text)