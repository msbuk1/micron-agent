"""Error handling utilities for micron tools.

Shim re-exporting the deep ErrorFormat module — keeps plugin import
`from micron.tools.error_handling import handle_error` green while the
single table lives in `micron/error_format.py`.
"""
from micron.error_format import format_error as _format_error
from micron.error_format import ok as success


def handle_error(tool_name: str, error: Exception, context: str = "") -> str:
    """Standardize error handling across all tools."""
    return _format_error(error, context, tool=tool_name)
