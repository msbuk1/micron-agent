---
name: patch_file
description: Apply multiple find-and-replace patches to a file sequentially.
---

# patch_file

Apply multiple text replacements to a file.

**Parameters:**
- `path` (required): File path relative to workdir
- `patches` (required): List of `{"old": "text", "new": "replacement"}` dicts

**Examples:**
- `patch_file('config.txt', [{'old': 'foo', 'new': 'bar'}])`
