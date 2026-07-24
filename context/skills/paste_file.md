---
name: paste_file
description: Save content to a file in context/uploads/. Auto-generates filename if not provided.
---

# paste_file

Save content to a file.

**Parameters:**
- `content` (required): The content to save
- `filename` (optional): Custom filename. Auto-generates `paste_<timestamp>.txt` if omitted.

**Examples:**
- `paste_file('hello world')` → saves to `paste_20260724_153000.txt`
- `paste_file('data', 'report.txt')` → saves to `report.txt`
