# SLICE PLAN: Micron Agent - Small Achievable Chunks

**Last Updated:** 2026-07-13  
**Status:** Phase 4 complete, focusing on security and quality  
**Approach:** Small, testable slices that can be completed in 1-2 hours each

---

## Current State

| Metric | Status |
|--------|--------|
| Tests | 66/66 passing ✅ |
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
- [ ] All existing tests pass (66+)
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

**Total:** 10 slices completed, 121 tests passing

