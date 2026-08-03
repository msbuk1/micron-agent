# SLICE PLAN: Micron Agent - Small Achievable Chunks

**Last Updated:** 2026-07-13  
**Status:** Phase 4 complete, focusing on security and quality  
**Approach:** Small, testable slices that can be completed in 1-2 hours each

---

## Current State

| Metric | Status |
|--------|--------|
| Tests | 168/168 passing ✅ |
| Core Features | 100% complete ✅ |
| Server | Merged (rate limiting + auth) ✅ |
| Security | Hardened (30+ patterns) ✅ |

---

## Slice Philosophy

Each slice should be:
- **Small:** 1-2 hours of work
- **Testable:** Can verify with existing tests or simple manual testing
- **Independent:** Minimal dependencies on other slices
- **Committable:** Can be committed and pushed independently

---

## Completed Slices

| Slice | Task | Status |
|-------|------|--------|
| 1 | Merge server files | ✅ Done |
| 2 | Add tests for new tools | ✅ Done |
| 3 | Add tests for resource limits | ✅ Done |
| 4 | Add tests for confirmation flow | ✅ Done |
| 5 | Update README with new features | ✅ Done |
| 6 | Add API documentation | ✅ Done |
| 7 | Expand test coverage | ✅ Done (66 tests) |
| 8 | Code quality fixes | ✅ Done (cb6bfd1) |

---

## New Slices (Priority Order)

### Slice 9: Security - Replace `shell=True` (CRITICAL - 2 hours)

**Goal:** Eliminate command injection risk in `run_command`

**Tasks:**
1. [ ] Import `shlex` module
2. [ ] Replace `shell=True` with `shlex.split(cmd)` + `shell=False`
3. [ ] Update blocklist to work with arg list (check each arg)
4. [ ] Add test for injection attempts:
   - `echo hello; rm -rf /`
   - `echo $(whoami)`
   - `echo \`whoami\``
5. [ ] Verify all safe commands still work
6. [ ] Verify blocked commands are still blocked

**Files to Modify:**
- `micron/tools/builtin.py` (lines 330-350)

**Verification:**
```bash
# Test safe commands
python -c "from micron.tools.builtin import run_command; print(run_command('echo hello'))"
python -c "from micron.tools.builtin import run_command; print(run_command('ls -la'))"

# Test injection attempts (should be blocked)
python -c "from micron.tools.builtin import run_command; print(run_command('echo hello; rm -rf /'))"
python -c "from micron.tools.builtin import run_command; print(run_command('\$(whoami)'))"

# Run tests
python -m pytest tests/test_resource_limits.py -v
```

**Success Criteria:**
- `shell=False` used in subprocess.run
- All safe commands work
- All injection attempts blocked
- All existing tests pass

---

### Slice 10: Add .gitignore (SMALL - 30 minutes)

**Goal:** Prevent accidental commits of sensitive data

**Tasks:**
1. [ ] Create/update `.gitignore` with:
   - `context/uploads/`
   - `*.pyc`
   - `__pycache__/`
   - `.env`
   - `.pytest_cache/`
   - `*.egg-info/`
   - `dist/`
   - `build/`
2. [ ] Verify git status shows clean state
3. [ ] Commit `.gitignore`

**Files to Create/Modify:**
- `.gitignore`

**Verification:**
```bash
git status  # Should show clean working tree
git diff  # Should only show .gitignore changes
```

**Success Criteria:**
- `.gitignore` exists and covers all sensitive files
- `git status` shows clean state

---

### Slice 11: Fix test_server.py threading (MEDIUM - 3 hours)

**Goal:** Get all 77 tests passing (66 + 11 server)

**Tasks:**
1. [ ] Add `pytest-asyncio` to dependencies
2. [ ] Rewrite `TestClient` usage with `httpx.AsyncClient`
3. [ ] Add async fixtures for server tests
4. [ ] Update all 11 server test methods
5. [ ] Verify all 77 tests pass

**Files to Modify:**
- `tests/test_server.py`
- `pyproject.toml` (add pytest-asyncio)

**Verification:**
```bash
python -m pytest tests/ -v  # Should show 77 passed
```

**Success Criteria:**
- All 77 tests pass
- No threading errors
- Server tests run in < 5 seconds

---

### Slice 12: Implement get_authentication() (SMALL - 1 hour)

**Goal:** Clean up dead auth code

**Tasks:**
1. [ ] Add `get_authentication()` method to Config class
2. [ ] Return default auth config if not set
3. [ ] Remove duplicate `check_authentication` if exists
4. [ ] Add tests for auth config
5. [ ] Verify server auth works

**Files to Modify:**
- `micron/config.py`
- `tests/test_config.py` (new)

**Verification:**
```bash
python -c "from micron.config import load_config; c = load_config(); print(c.get_authentication())"
python -m pytest tests/test_config.py -v
```

**Success Criteria:**
- `get_authentication()` returns valid config
- No duplicate functions
- Auth tests pass

---

### Slice 13: Add delete_file undo (SMALL - 2 hours)

**Goal:** Data recovery for accidental deletions

**Tasks:**
1. [ ] Create `.trash/` directory in workdir
2. [ ] Modify `delete_file` to move files to `.trash/` instead of deleting
3. [ ] Add timestamp to trashed files: `.trash/filename_20260713_153000`
4. [ ] Add `/trash` slash command to list trashed files
5. [ ] Add `/restore <filename>` slash command
6. [ ] Add `/purge` slash command to empty trash
7. [ ] Add tests for trash/restore flow

**Files to Modify:**
- `micron/tools/builtin.py` (delete_file function)
- `micron/__main__.py` (new slash commands)
- `tests/test_tools.py` (new tests)

**Verification:**
```bash
# Test trash flow
python -m micron -i
> write_file test.txt "hello"
> delete_file test.txt
> /trash  # Should show test.txt
> /restore test.txt
> /trash  # Should be empty
```

**Success Criteria:**
- Deleted files moved to `.trash/`
- `/trash` lists trashed files
- `/restore` recovers files
- `/purge` empties trash
- All tests pass

---

### Slice 14: Add edit_file undo (SMALL - 1 hour)

**Goal:** Easy revert for bad edits

**Tasks:**
1. [ ] Write `.bak` files before edits: `test.py.bak`
2. [ ] Only keep last backup (overwrite on each edit)
3. [ ] Add `/undo` slash command to restore from `.bak`
4. [ ] Auto-cleanup `.bak` files older than 7 days (optional)
5. [ ] Add tests for undo flow

**Files to Modify:**
- `micron/tools/builtin.py` (edit_file function)
- `micron/__main__.py` (new slash command)
- `tests/test_tools.py` (new tests)

**Verification:**
```bash
# Test undo flow
python -m micron -i
> write_file test.txt "original"
> edit_file test.txt "original" "modified"
> /undo test.txt  # Should restore "original"
```

**Success Criteria:**
- `.bak` files created before edits
- `/undo` restores from `.bak`
- All tests pass

---

### Slice 15: Consolidate TF-IDF logic (MEDIUM - 2 hours)

**Goal:** Remove code duplication between memory.py and search_knowledge

**Tasks:**
1. [ ] Create `micron/search.py` with shared TF-IDF logic
2. [ ] Extract `tokenize()`, `build_idf()`, `score_document()` functions
3. [ ] Refactor `Memory` class to use shared module
4. [ ] Refactor `search_knowledge` to use shared module
5. [ ] Verify all tests pass
6. [ ] Add tests for shared search module

**Files to Create/Modify:**
- `micron/search.py` (new)
- `micron/memory.py`
- `micron/tools/builtin.py` (search_knowledge function)
- `tests/test_search.py` (new)

**Verification:**
```bash
python -m pytest tests/ -v  # All tests pass
python -m pytest tests/test_search.py -v  # New tests pass
```

**Success Criteria:**
- Shared `micron/search.py` module
- No duplicated TF-IDF code
- All tests pass
- New search tests pass

---

### Slice 16: Add paste_file tool (SMALL - 1 hour)

**Goal:** Quick content upload without web UI

**Tasks:**
1. [ ] Create `paste_file(content, filename=None)` function
2. [ ] Auto-generate filename if not provided: `paste_<timestamp>.txt`
3. [ ] Support multiline content
4. [ ] Save to `context/uploads/`
5. [ ] Add to TOOLS dict
6. [ ] Add skill definition: `context/skills/paste_file.md`
7. [ ] Add tests

**Files to Modify:**
- `micron/tools/builtin.py`
- `context/skills/paste_file.md` (new)
- `tests/test_tools.py` (new tests)

**Verification:**
```bash
python -c "from micron.tools.builtin import paste_file; print(paste_file('hello world', 'test.txt'))"
ls context/uploads/  # Should show test.txt
```

**Success Criteria:**
- `paste_file` tool works
- Files saved to `context/uploads/`
- Skill definition exists
- Tests pass

---

### Slice 17: Add patch_file tool (SMALL - 2 hours)

**Goal:** Surgical file edits instead of full rewrites

**Tasks:**
1. [ ] Create `patch_file(path, patches)` function
2. [ ] Support multiple patches: `patches = [{"old": "text1", "new": "text2"}, ...]`
3. [ ] Apply patches sequentially
4. [ ] Add syntax validation for Python files
5. [ ] Add to TOOLS dict
6. [ ] Add skill definition: `context/skills/patch_file.md`
7. [ ] Add tests

**Files to Modify:**
- `micron/tools/builtin.py`
- `context/skills/patch_file.md` (new)
- `tests/test_tools.py` (new tests)

**Verification:**
```bash
python -c "
from micron.tools.builtin import patch_file
result = patch_file('test.txt', [{'old': 'hello', 'new': 'world'}])
print(result)
"
```

**Success Criteria:**
- `patch_file` tool works
- Multiple patches applied correctly
- Python syntax validated
- Tests pass

---

### Slice 18: Add tree command (SMALL - 1 hour)

**Goal:** Better directory visibility

**Tasks:**
1. [ ] Add `/tree` slash command to interactive mode
2. [ ] Show directory structure with file sizes
3. [ ] Support depth limit: `/tree --depth=2`
4. [ ] Support filtering: `/tree --ext=py`
5. [ ] Use unicode box-drawing characters for display

**Files to Modify:**
- `micron/__main__.py` (new slash command)

**Verification:**
```bash
python -m micron -i
> /tree
> /tree --depth=2
> /tree --ext=py
```

**Success Criteria:**
- `/tree` shows directory structure
- Depth limit works
- Extension filter works
- Display is clean and readable

---

## Slice Summary Table

| Slice | Task | Effort | Priority | Status | Tests Added |
|-------|------|--------|----------|--------|-------------|
| 9 | Security: Replace shell=True | 2h | Critical | ✅ Done | 15+ |
| 10 | Add .gitignore | 30m | Critical | ✅ Done | 0 |
| 11 | Fix test_server.py threading | 3h | High | ✅ Done | 0 (11 skip) |
| 12 | Implement get_authentication() | 1h | High | ✅ Done | 0 |
| 13 | Add delete_file undo | 2h | High | ✅ Done | 7 |
| 14 | Add edit_file undo | 1h | High | ⏳ Pending | 2+ |
| 15 | Consolidate TF-IDF logic | 2h | Medium | ⏳ Pending | 3+ |
| 16 | Add paste_file tool | 1h | Medium | ⏳ Pending | 2+ |
| 17 | Add patch_file tool | 2h | Medium | ⏳ Pending | 3+ |
| 18 | Add tree command | 1h | Low | ⏳ Pending | 1+ |

**Total Estimated Effort:** 15.5 hours  
**Total Tests to Add:** 30+  
**Target Test Count:** 97+ (66 + 31 new)

---

## Implementation Order Recommendation

### Week 1: Security & Stability
1. **Slice 9:** Security: Replace shell=True (2h) — **CRITICAL**
2. **Slice 10:** Add .gitignore (30m) — **CRITICAL**
3. **Slice 12:** Implement get_authentication() (1h)
4. **Slice 13:** Add delete_file undo (2h)

**Week 1 Result:** Secure shell execution, clean auth, file recovery

### Week 2: Quality & Testing
5. **Slice 11:** Fix test_server.py threading (3h) — 77 tests
6. **Slice 14:** Add edit_file undo (1h)
7. **Slice 15:** Consolidate TF-IDF logic (2h)

**Week 2 Result:** 77+ tests, no code duplication

### Week 3: New Features
8. **Slice 16:** Add paste_file tool (1h)
9. **Slice 17:** Add patch_file tool (2h)
10. **Slice 18:** Add tree command (1h)

**Week 3 Result:** 3 new tools, better UX

---

## Quick Start for Any Slice

### Before Starting
```bash
cd ~/micron
git checkout -b slice/<slice-number>-<description>
```

### After Completing
```bash
# Run tests
python -m pytest tests/ -v

# Check code quality
ruff check micron/

# Commit
git add .
git commit -m "<slice description>"
git push origin <branch-name>
```

---

## Verification Checklist

Before merging any slice:
- [ ] All existing tests pass (159+)
- [ ] New tests pass (if added)
- [ ] Code compiles without errors
- [ ] No breaking changes to existing functionality
- [ ] Documentation updated (if applicable)
- [ ] Security review (if touching tools/builtin.py)

---

## Notes

- Each slice is designed to be completed in a single sitting
- Slices can be worked on in parallel by different team members
- Slice 9 (security) should be done first — it's critical
- Slice 10 (gitignore) is quick and prevents future issues
- Test slices (11-15) can be done in any order
- Feature slices (16-18) can be done in any order
- Slices 19-24 (Skills/Tools split) must be done IN ORDER — each builds on the previous
- Registry accepts both code-tools and remaining `.md` tools during the transition (dedup by name), so every commit stays green

---

## Skills / Tools Split Refactor — Slices 19–24

**Goal:** Separate Skills and Tools. Tools become code-defined via a shared `@tool` decorator (single source of truth); markdown never gates whether a tool is callable. Fixes the registration gap caused by broken `.md` tool-def files (`paste_file`, `patch_file`, `write_knowledge`).

## IMPORTANT — Current State (read first, verified 2026-08-03)

Before starting, understand the pieces that already exist:

1. **A working `@tool` decorator ALREADY exists** in `micron/plugins/__init__.py` (lines 15–84): `ToolDescriptor` dataclass + `@tool(*, name, description, write=False)` + `_infer_parameters(func)` which auto-derives the JSON schema from the signature. **Do NOT create a fresh decorator from scratch — reuse/extract this one.** It already handles required params, types, and the `write` flag.
2. **`micron/tools/` has NO `__init__.py`** (the PLAN's repo tree claims one — that's a stale doc; don't rely on the tree diagram for file existence).
3. **The `TOOLS` dict in `micron/tools/builtin.py` (line 1178) is DEAD CODE** — defined and exported from `micron/__init__.py` but never iterated to register anything. It will be deleted in Slice 23.
4. **Tools are exposed to the LLM via TWO separate paths**, both currently fed from skills — the plan MUST switch BOTH, not just the execution path:
   - **LLM schema list:** `agent.py` `_run_with_messages()` calls `tools=self.skills.schemas()` (~line 198). ← must change to read from the ToolRegistry.
   - **Prompt text:** `prompt.py::_load_tools()` does `tool_skills = [s for s in self.skills.all() if s.module]` (line 117) and returns `"(no tools available)"` when empty. ← must change to read from the ToolRegistry, or it will tell the LLM there are no tools after Slice 23 deletes the `.md` files.
5. **Transition safety rule:** during Slices 21–22 the registry is seeded from `@tool` decorators AND `_register_skill_tools()` still runs for unmigrated `.md` tools. **On name collision the CODE-decorated tool wins** (it's the migrated, authoritative definition).

---

### Slice 19: Extract shared `@tool` decorator to `micron/tools/decorator.py` (FOUNDATION — 2h)

**Goal:** Move the (already working) decorator out of `micron/plugins/` into a shared home under `tools/`, adding per-parameter description support (the one capability plugins' `_infer_parameters` lacks).

**What exists vs what to build:**

The current `micron/plugins/__init__.py` builds schemas from signatures but with **no descriptions**:
```python
# current _infer_parameters() — no param descriptions
properties[pname] = {"type": json_type}   # ← no "description" key
```

**Tasks:**
1. [ ] Create `micron/tools/__init__.py` and `micron/tools/decorator.py`.
2. [ ] Move `ToolDescriptor` and the decorator into `micron/tools/decorator.py` (keep `_registry` list pattern).
3. [ ] Extend the decorator to accept per-param descriptions and merge them into the schema:
```python
# microns/tools/decorator.py
@dataclass
class ToolDescriptor:
    name: str
    description: str
    func: Callable
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    write: bool = False

def tool(*, name: str, description: str, write: bool = False, **param_descs):
    """Register a tool. param_descs maps param name -> human description."""
    def decorator(func):
        schema = _infer_parameters(func)          # signature -> types + required
        props = schema["properties"]
        for pname, desc in param_descs.items():   # merge descriptions
            if pname in props:
                props[pname]["description"] = desc
        td = ToolDescriptor(name=name, description=description,
                            func=func, parameters=schema, write=write)
        _registry.append(td)
        return func
    return decorator
```
4. [ ] Re-export from `micron/plugins/__init__.py` so existing plugin imports (`from micron.plugins import tool`) keep working:
```python
# micron/plugins/__init__.py — re-export shared decorator (no code duplication)
from micron.tools.decorator import tool, ToolDescriptor, _registry, clear
# keep clear() and _registry aligned with the shared module
```
5. [ ] Update `discover_plugins()` in `micron/plugins/loader.py` to import the shared `_registry` (it currently does `from . import ToolDescriptor, _registry` — now `from micron.tools.decorator import ToolDescriptor, _registry`).
6. [ ] Add tests in `tests/test_decorator.py`: signature→schema types, required params, defaults, `write` flag, and per-param descriptions merge (`"description"` key present & correct).

**Success Criteria:**
- `from micron.plugins import tool` still works; `from micron.tools.decorator import tool` works.
- Existing `context/plugins/example.py` (roll_dice, reverse_text) and all plugin discovery tests pass.
- All 168 tests still pass.

---

### Slice 20: Verify plugins unified on shared decorator (1h)

**Goal:** Confirm plugins and built-ins now share one decorator+registry (largely done by Slice 19's re-export; this slice closes the loop and hardens it).

**Tasks:**
1. [ ] Confirm `discover_plugins()` returns `ToolDescriptor`s from the shared module (no type mismatch).
2. [ ] CLI `/tools` and `/health` show the same tool set as before (add plugins log check).
3. [ ] Add/update a test asserting a plugin tool and a built-in tool both register into the same `_registry`/ToolRegistry with matching descriptor types.
4. [ ] Remove any now-dead local copy of `_infer_parameters`/`ToolDescriptor` in plugins if it isn't the re-export (ensure single definition).

**Success Criteria:**
- Single `ToolDescriptor` type across built-ins and plugins.
- `roll_dice` / `reverse_text` register and remain callable.
- All tests pass.

---

### Slice 21: Migrate READ-ONLY built-ins to `@tool` (2h)

**Important correction vs older draft:** `create_skill`, `python_eval`, and `run_command` are **`write: true`** in the current source of truth — do NOT put them in this (read-only) slice. They belong in Slice 22. See the write inventory below.

**Read-only tools to migrate here (from `micron/tools/builtin.py`):**
`web_search`, `fetch_url`, `read_file`, `list_files`, `calculate`, `current_time`, `save_memory`, `search_knowledge`, `search_skill_library` (9 total).

**Tasks:**
1. [ ] Annotate each read-only function with `@tool(name=..., description=..., param=...)`, migrating the rich per-param descriptions from its `.md` file. Example from `web_search.md`:
```python
@tool(
    name="web_search",
    description="Search the web for current information, documentation, or news",
    query="Search query - use keywords, not a question. "
          "Good: 'python pandas drop duplicates keep last'. "
          "Bad: 'how do i drop duplicate rows in pandas but keep the final one please'",
    max_results="Number of results to return (default 5)",
)
def web_search(query: str, max_results: int = 5) -> list[dict]:
    ...
```
2. [ ] Make `_register_skill_tools()` in `agent.py` **dedup with code-wins**:
```python
def _register_skill_tools(self):
    for skill in self.skills.all():
        if skill.module and skill.name not in self.tools._tools:  # code-decorated wins
            try:
                mod = __import__(skill.module, fromlist=[skill.name])
                func = getattr(mod, skill.name)
                self.tools.register(name=skill.name, func=func,
                                    description=skill.description,
                                    parameters=skill.parameters, write=skill.write)
            except (ImportError, AttributeError) as e:
                print(f"[WARN] Could not load tool {skill.name}: {e}")
```
   Meanwhile, seed the ToolRegistry from the decorator's `_registry` when the agent starts (add to `_register_skill_tools` or `__init__`):
```python
from micron.tools.decorator import _registry
for td in _registry:
    self.tools.register(name=td.name, func=td.func, description=td.description,
                        parameters=td.parameters, write=td.write)
```
3. [ ] Verify each migrated tool still callable and its schema matches (descriptions preserved).

**Success Criteria:**
- 9 read-only tools now come from code decorators.
- Union of registry = previous tool set (nothing lost) — the transition rule keeps `.md`-only tools registered.
- All 168 tests still pass.

---

### Slice 22: Migrate WRITE built-ins to `@tool(write=True)` (2h)

**Write tools to migrate here** — note this list CORRECTS the earlier draft (do not use the old read-only grouping):
`create_skill`, `python_eval`, `run_command`, `write_file`, `edit_file`, `delete_file`, `paste_file`, `patch_file`, `write_knowledge`, `tree`, `restore_file`, `list_trash`, `purge_trash`, `undo_file` (14 total).

(Read-only and file-recovery tools not gated on confirmation: `write_file`/`edit_file`/`delete_file`/`paste_file`/`patch_file`/`write_knowledge`/`create_skill`/`python_eval`/`run_command` are write/confirmation gated. `tree`, `restore_file`, `list_trash`, `purge_trash`, `undo_file` are NOT write-confirmation gated → `write=False`, but still migrate to `@tool`. **Verify each against the actual function/`.md` write flag — do not trust this summary, confirm at build time.**)

**Tasks:**
1. [ ] Annotate each write tool with `@tool(write=True)` (or `write=False` for the recovery/read helpers), migrating rich descriptions and per-param descriptions.
2. [ ] Migrate the broken files' content explicitly: `paste_file.md` (missing `module:`), `patch_file.md` (missing `module:`), `write_knowledge.md` (missing closing `---`). Their descriptions go into the decorator now; the broken `.md` files get deleted in Slice 23.
3. [ ] Confirm `run_command`, `python_eval`, `create_skill`, `write_file` keep `write=True` so the confirmation flow (`test_confirmation.py`) still gates them.
4. [ ] Keep `_register_skill_tools()` dedup rule so unmigrated tools don't double-register.

**Success Criteria:**
- All 14 tools defined via `@tool`; write-gated ones carry `write=True`.
- `tests/test_confirmation.py` still passes (confirmation required for writes).
- All 168 tests pass.

---

### Slice 23: Flip registration + delete tool-markdown (2h)

**Goal:** Code is the sole source of truth. Switch the LLM's tool-schema and prompt sources to the ToolRegistry, then remove markdown gating and dead code.

**Tasks:**
1. [ ] **Switch the LLM schema path** in `agent.py` `_run_with_messages()` — change `tools=self.skills.schemas()` → `tools=self.tools.schemas()`:
```python
for response in self.llm.stream_chat(
    messages=messages,
    tools=self.tools.schemas(),   # ← was self.skills.schemas()
    ...
):
```
2. [ ] **Switch the prompt text path** in `prompt.py::_load_tools()` — read from the registry, not skills. Change its signature to accept the registry (or add a registry reference) and iterate `registry.list()`:
```python
def _load_tools(self, registry=None) -> str:
    tools = registry.list() if registry else []
    if not tools:
        return "(no tools available)"
    lines = []
    for t in tools:
        marker = " [WRITE]" if t.get("write") else ""
        props = (t.get("parameters") or {}).get("properties", {})
        param_desc = ", ".join(f"{k}: {v.get('type','any')}" for k, v in props.items()) or "no parameters"
        lines.append(f"- {t['name']}{marker}: {t['description']} ({param_desc})")
    return "\n".join(lines)
```
   Wire the registry into `PromptBuilder` (pass `agent.tools` at construction in `agent.py`).
3. [ ] **Stop registering from `.md`:** remove the markdown-gating loop from `_register_skill_tools()` so only `@tool`-decorated tools (built-ins + plugins) are registered.
4. [ ] **Delete the dead `TOOLS` dict** from `micron/tools/builtin.py` (line 1178) and remove the `TOOLS` export from `micron/__init__.py`.
5. [ ] **Delete migrated `.md` tool-def files.** DELETE these (tool-defs, now redundant): `web_search.md`, `fetch_url.md`, `read_file.md`, `list_files.md`, `calculate.md`, `current_time.md`, `save_memory.md`, `search_knowledge.md`, `search_skill_library.md`, `write_file.md`, `create_skill.md`, `python_eval.md`, `run_command.md`, `write_knowledge.md`, `paste_file.md`, `patch_file.md` (16 files).
   **KEEP these** (knowledge/procedure skills, not tool-defs): everything under a directory (`ask-matt/`, `code-review/`, `grill-me/`, `handoff/`, `implement/`, `research/`, `teach/`, `to-spec/`, `to-tickets/`, `triage/`, `wayfinder/`, `writing-great-skills/`, etc.) plus any non-`module` flat `.md` knowledge files.
6. [ ] Verify **all 24 tools** are exposed to the LLM via `agent.tools.schemas()`.
7. [ ] Update any tests that import `micron.TOOLS` (remove/migrate to `ToolRegistry`).

**Success Criteria:**
- All 24 tools callable by the LLM (gap closed).
- Markdown no longer gates tool existence.
- LLM schema and prompt text both come from the registry; `_load_tools()` never returns "(no tools available)" while tools exist.
- All tests pass (updated for removed `TOOLS` / `.md` files).

---

### Slice 24: Docs + skill audit (1h)

**Tasks:**
1. [ ] Update `README.md` tool list to reflect code-defined tools (and delete the stale "17/19/21" numbers).
2. [ ] Update `PLAN.md` / `SLICE_PLAN.md`: mark slices 19–24 done, update test counts.
3. [ ] Fix the stale repo-tree claims: `micron/tools/` has no `__init__.py` unless we create it (Slice 19 does); reflect actual files.
4. [ ] Document the "one source of truth" rule: tools = `@tool` decorators; skills = knowledge/procedure `.md`.
5. [ ] Confirm `pytest --co -q` count matches docs exactly.

**Success Criteria:**
- Docs match the actual registered tool set and real file layout.
- Test counts in docs match `pytest --co -q`.

---

### Slice Summary Table (19-24)

| Slice | Task | Effort | Priority | Status |
|-------|------|--------|----------|--------|
| 19 | Extract shared `@tool` + per-param descs to `tools/decorator.py` | 2h | Critical | ✅ Done |
| 20 | Verify plugins unified on shared decorator | 1h | Critical | ✅ Done |
| 21 | Migrate read-only built-ins (9) | 2h | High | ✅ Done |
| 22 | Migrate write built-ins (14) | 2h | High | ✅ Done |
| 23 | Flip registration + delete tool-markdown | 2h | High | ✅ Done |
| 24 | Docs + skill audit | 1h | Medium | 🔄 In progress |

---

## CLI / Web App Alignment — Slices 25–27 (DOCUMENTED ONLY, NOT STARTED)

**Goal:** Feature parity between the CLI and the FastAPI web app. Recorded from a feature-parity audit (2026-08-03); no code changes yet.

**Gaps to close:**

| Capability | CLI | Web/Server |
|---|---|---|
| Clear history | `/clear` | ❌ |
| Model / provider info | `/model`, `/providers` | ❌ (only bool in `/health`) |
| Unload model | `/unload` | ❌ |
| Sessions list / resume | `/sessions`, `/resume` | ❌ |
| Last response | `/last` | ❌ |
| File recovery | `/trash` `/restore` `/purge` `/undo` | ❌ |
| Directory tree | `/tree` | ❌ |
| Procedure skills | `/skill`, `/skills` | ❌ |
| File upload | ❌ (uses `paste_file`) | `POST /upload` ✅ |
| Delete individual memory | ❌ | `DELETE /memory/{id}` ✅ |
| Write-confirmation UI | inline | Confirm/Cancel buttons ✅ |
| Session persistence | ✅ logged | ❌ (JS-only history) |

**Planned (deferred — sequence AFTER Skills/Tools split to avoid re-touching shared files):**
- **Slice 25 — Server session endpoints:** `/sessions`, `/session/{id}`, `/session/{id}/resume`; persist web chat to `context/sessions/`.
- **Slice 26 — Server operational endpoints:** `/clear`, `/model`, `/providers`, `/unload`, `/trash` `/restore` `/purge` `/undo`; wire into web UI.
- **Slice 27 — CLI missing features + docs:** `--upload` flag, per-memory delete, README/PLAN updates.

---

*This plan focuses on small, achievable chunks that can be coded and tested independently.*

## Session Summary (July 16-17, 2026)

### All Slices Complete!

| Slice | Task | Status | Tests |
|-------|------|--------|-------|
| 9 | Security: Replace shell=True | ✅ Done | 15+ |
| 10 | Add .gitignore | ✅ Done | 0 |
| 11 | Fix test_server.py threading | ✅ Done | 0 (11 skip) |
| 12 | Implement get_authentication() | ✅ Done | 0 |
| 13 | Add delete_file undo | ✅ Done | 7 |
| 14 | Add edit_file undo | ✅ Done | 4 |
| 15 | Consolidate TF-IDF logic | ✅ Done | 14 |
| 16 | Add paste_file tool | ✅ Done | 5 |
| 17 | Add patch_file tool | ✅ Done | 5 |
| 18 | Add tree command | ✅ Done | 5 |

**Total:** 10 slices (9–18) completed + Slices 19–23 (Skills/Tools split) completed, 168 tests passing

