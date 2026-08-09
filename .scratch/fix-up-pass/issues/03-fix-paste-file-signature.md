# 03 — Fix paste_file Signature + Tests

**What to build:** Change `paste_file(path, content, line=0)` to `paste_file(content, filename=None)` with auto-generated `paste_<timestamp>.txt` filenames saved to `context/uploads/`. Update tests to match.

**Blocked by:** None — can start immediately.

**Status:** ✅ done — verified in code (2026-08-03)

- [x] `paste_file(content, filename=None)` — content-first, optional filename
- [x] Auto-generates `paste_<timestamp>.txt` when no filename provided
- [x] Saves to `context/uploads/`
- [x] Tests cover: append to existing file, new file, auto-generated filename, directory creation
