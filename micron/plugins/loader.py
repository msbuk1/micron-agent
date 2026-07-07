"""Plugin loader — discovers and imports plugin modules from a directory.

Scans for ``.py`` files (except ``__init__.py`` and ``_test`` files),
imports each module, and collects any tool descriptors registered via
the ``@tool`` decorator.
"""

import importlib.util
import logging
from pathlib import Path
from typing import List

from . import ToolDescriptor, _registry

logger = logging.getLogger(__name__)


def discover_plugins(plugin_dir: str | Path) -> List[ToolDescriptor]:
    """Scan *plugin_dir* for ``.py`` files, import them, and return registered tool descriptors.

    Each module that uses ``@tool`` registers itself into the shared ``_registry`` via import
    side-effect.  After discovery, the registry is returned and cleared so a subsequent call
    doesn't double-count.

    Args:
        plugin_dir: Directory containing plugin ``.py`` files.

    Returns:
        List of ``ToolDescriptor`` objects registered by the discovered plugins.
    """
    plugin_dir = Path(plugin_dir)
    if not plugin_dir.exists():
        return []

    count_before = len(_registry)

    for f in sorted(plugin_dir.glob("*.py")):
        # Skip __init__, test helpers, and non-module files
        if f.name.startswith("_") or f.name.endswith("_test.py"):
            continue

        try:
            spec = importlib.util.spec_from_file_location(f.stem, f)
            if spec is None or spec.loader is None:
                logger.warning("Could not load plugin %s: spec_from_file_location failed", f.name)
                continue

            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            logger.warning("Failed to load plugin %s: %s", f.name, e)

    # Collect newly registered descriptors
    new_descriptors = _registry[count_before:]
    return new_descriptors