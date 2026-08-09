# 05 — Add /tree Slash Command + Ext Filter

**What to build:** Add `/tree` to interactive mode so users can visualize directory structure. Add `--ext=py` filtering support to the `tree()` function.

**Blocked by:** None — can start immediately.

**Status:** ✅ done — verified in code (2026-08-03)

- [x] `/tree` command works in interactive mode
- [x] `/tree --depth=2` limits depth
- [x] `/tree --ext=py` filters by extension
- [x] Tests cover: simple tree, nested dirs, max_depth, ext filter, empty dir
