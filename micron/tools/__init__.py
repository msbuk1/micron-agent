"""Tool system for micron — shared @tool decorator + tool registry."""
# Importing builtin triggers its @tool decorations to run, so the shared
# registry is populated. Without this, the tool functions' decorators would
# never execute and built-in tools would not register.
from micron.tools import builtin  # noqa: F401
