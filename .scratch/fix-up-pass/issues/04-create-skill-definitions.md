# 04 — Create Skill Definitions for paste_file and patch_file

**What to build:** Create `context/skills/paste_file.md` and `context/skills/patch_file.md` so the agent can discover these tools through the skill system.

**Blocked by:** None — can start immediately.

**Status:** ⚠️ superseded — files exist but are broken; being resolved by Skills/Tools split (Slices 19–23)

> These `.md` files exist on disk but are defective: `paste_file.md` and `patch_file.md` are missing the `module:` frontmatter field, so they never register as callable tools; `write_knowledge.md` is missing its closing `---`, so it fails to load entirely. Under the Skills/Tools split (Slices 19–23), tool definitions move into code via `@tool` decorators and these `.md` tool-def files get deleted. Do NOT fix them in isolation — Slice 23 removes them.

- [x] `context/skills/paste_file.md` exists (but broken — missing `module:`)
- [x] `context/skills/patch_file.md` exists (but broken — missing `module:`)
- [x] Both files follow the same format as existing skill definitions in `context/skills/` (partial — missing required fields)
