# SLICE PLAN: Micron Agent - Small Achievable Chunks

**Last Updated:** 2026-07-12  
**Status:** All quick wins complete, focusing on remaining tasks  
**Approach:** Small, testable slices that can be completed in 1-2 hours each

---

## Current State

| Metric | Status |
|--------|--------|
| Tests | 37/37 passing ✅ |
| Quick Wins | 3/3 complete ✅ |
| Core Features | 100% complete ✅ |

---

## Slice Philosophy

Each slice should be:
- **Small:** 1-2 hours of work
- **Testable:** Can verify with existing tests or simple manual testing
- **Independent:** Minimal dependencies on other slices
- **Committable:** Can be committed and pushed independently

---

## Remaining Slices (Priority Order)

### Slice 1: Merge Server Files (MEDIUM - 2 hours)

**Goal:** Eliminate code duplication between `server.py` and `server_new.py`

**Tasks:**
1. [ ] Compare both files line by line
2. [ ] Identify unique features in each:
   - `server.py`: Existing endpoints, SSE streaming
   - `server_new.py`: Rate limiting, authentication
3. [ ] Merge `server_new.py` features into `server.py`:
   - Copy rate limiting logic
   - Copy authentication logic
   - Update imports
4. [ ] Test all endpoints work:
   - GET /health
   - GET /tools
   - POST /chat (streaming and non-streaming)
   - POST /upload
   - POST /memory
   - GET /memory
5. [ ] Remove `server_new.py`
6. [ ] Update any references to `server_new.py`

**Files to Modify:**
- `micron/server.py` (primary)
- Remove `micron/server_new.py`

**Verification:**
```bash
# Start server
python -m micron --server --port 8000 &

# Test endpoints
curl http://localhost:8000/health
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"message": "test", "stream": false}'

# Run server tests
python -m pytest tests/test_server.py -v
```

**Success Criteria:**
- All server tests pass
- All endpoints functional
- Single server file

---

### Slice 2: Add Tests for New Tools (SMALL - 1 hour)

**Goal:** Add tests for delete_file, edit_file, list_skills

**Tasks:**
1. [ ] Create `tests/test_tools.py`
2. [ ] Add test for `delete_file`:
   - Test deleting existing file
   - Test deleting non-existing file
   - Test path traversal protection
3. [ ] Add test for `edit_file`:
   - Test replacing text in file
   - Test syntax validation for Python files
   - Test auto-revert on syntax error
4. [ ] Add test for `list_skills`:
   - Test listing all skills
   - Test filtering by query

**Files to Create:**
- `tests/test_tools.py`

**Verification:**
```bash
python -m pytest tests/test_tools.py -v
```

**Success Criteria:**
- 3+ new tests passing
- All existing tests still pass

---

### Slice 3: Add Tests for Resource Limits (SMALL - 1 hour)

**Goal:** Test that resource limits work in run_command

**Tasks:**
1. [ ] Add test for CPU limit:
   - Set MICRON_CMD_MAX_CPU=1
   - Run command that takes >1 second
   - Verify it's killed
2. [ ] Add test for memory limit:
   - Set MICRON_CMD_MAX_MEMORY_MB=1
   - Run command that allocates >1MB
   - Verify it's killed
3. [ ] Add test for command length limit:
   - Try command >500 characters
   - Verify it's rejected
4. [ ] Add test for blocklist:
   - Try `rm -rf /`
   - Try `sudo rm`
   - Verify all blocked

**Files to Modify:**
- `tests/test_tools.py` (add to Slice 2 file)

**Verification:**
```bash
python -m pytest tests/test_tools.py::test_resource_limits -v
python -m pytest tests/test_tools.py::test_command_blocklist -v
```

**Success Criteria:**
- 4+ new tests passing
- Resource limits working correctly

---

### Slice 4: Add Tests for Confirmation Flow (SMALL - 1 hour)

**Goal:** Test write tool confirmation flow

**Tasks:**
1. [ ] Add test for confirmation_required event:
   - Call agent with write tool
   - Verify confirmation_required event emitted
   - Verify pending_writes list populated
2. [ ] Add test for confirmed write:
   - Call agent with confirm=True and pending_tool_calls
   - Verify write executes
3. [ ] Add test for cancelled write:
   - Call agent with confirm=False
   - Verify write doesn't execute

**Files to Modify:**
- `tests/test_agent.py` (add new tests)

**Verification:**
```bash
python -m pytest tests/test_agent.py::test_confirmation_flow -v
```

**Success Criteria:**
- 3+ new tests passing
- Confirmation flow working correctly

---

### Slice 5: Update README with New Features (SMALL - 1 hour)

**Goal:** Document all completed features

**Tasks:**
1. [ ] Add new tools to README:
   - delete_file
   - edit_file
   - list_skills
2. [ ] Add resource limits section:
   - Environment variables
   - Default values
   - Examples
3. [ ] Add confirmation flow section:
   - How it works
   - CLI behavior
   - Server behavior
4. [ ] Update feature list
5. [ ] Update configuration examples

**Files to Modify:**
- `README.md`

**Verification:**
- Manual review
- All links work
- Examples are correct

**Success Criteria:**
- README up to date
- All features documented

---

### Slice 6: Add API Documentation (SMALL - 1 hour)

**Goal:** Document server API endpoints

**Tasks:**
1. [ ] Add API endpoints section to README:
   - GET /health
   - GET /tools
   - POST /chat
   - POST /upload
   - POST /memory
   - GET /memory
   - POST /memory/search
   - DELETE /memory/{id}
   - POST /skills/reload
2. [ ] Add example requests for each endpoint
3. [ ] Add authentication examples
4. [ ] Add rate limiting notes

**Files to Modify:**
- `README.md`

**Verification:**
- Manual review
- Examples work when tested

**Success Criteria:**
- All endpoints documented
- Examples are testable

---

### Slice 7: Expand Test Coverage (MEDIUM - 2 hours)

**Goal:** Add more comprehensive tests

**Tasks:**
1. [ ] Add tests for error handling:
   - Test handle_error function
   - Test success function
   - Test format_tool_result function
2. [ ] Add tests for security:
   - Test path traversal protection
   - Test all blocklist patterns
3. [ ] Add integration tests:
   - Test full agent workflow
   - Test multi-tool sequence
4. [ ] Add edge case tests:
   - Empty inputs
   - Invalid inputs
   - Missing files

**Files to Create/Modify:**
- `tests/test_error_handling.py`
- `tests/test_security.py`
- `tests/test_integration.py`

**Verification:**
```bash
python -m pytest tests/ -v  # Should show 50+ tests
```

**Success Criteria:**
- 50+ total tests
- All tests passing

---

## Slice Summary Table

| Slice | Task | Effort | Priority | Status | Tests Added |
|-------|------|--------|----------|--------|-------------|
| 1 | Merge server files | 2h | Medium | ⏳ Pending | 0 |
| 2 | Add tests for new tools | 1h | Medium | ⏳ Pending | 3+ |
| 3 | Add tests for resource limits | 1h | Medium | ⏳ Pending | 4+ |
| 4 | Add tests for confirmation flow | 1h | Medium | ⏳ Pending | 3+ |
| 5 | Update README with new features | 1h | Low | ⏳ Pending | 0 |
| 6 | Add API documentation | 1h | Low | ⏳ Pending | 0 |
| 7 | Expand test coverage | 2h | Medium | ⏳ Pending | 10+ |

**Total Estimated Effort:** 9-10 hours
**Total Tests to Add:** 20+
**Target Test Count:** 50+

---

## Implementation Order Recommendation

### Week 1: Core Stability
1. **Slice 1:** Merge server files (2h)
2. **Slice 2:** Add tests for new tools (1h)
3. **Slice 3:** Add tests for resource limits (1h)
4. **Slice 4:** Add tests for confirmation flow (1h)

**Week 1 Result:** Single server, 40+ tests, all features tested

### Week 2: Documentation
5. **Slice 5:** Update README (1h)
6. **Slice 6:** Add API documentation (1h)
7. **Slice 7:** Expand test coverage (2h)

**Week 2 Result:** 50+ tests, comprehensive documentation

---

## Quick Start for Any Slice

### Before Starting
```bash
cd /workspace/msbuk1__micron-agent
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
- [ ] All existing tests pass (37+)
- [ ] New tests pass (if added)
- [ ] Code compiles without errors
- [ ] No breaking changes to existing functionality
- [ ] Documentation updated (if applicable)

---

## Notes

- Each slice is designed to be completed in a single sitting
- Slices can be worked on in parallel by different team members
- Slice 1 (merge server files) should be done first to avoid merge conflicts
- Test slices (2-4, 7) can be done in any order
- Documentation slices (5-6) can be done in any order

---

*This plan focuses on small, achievable chunks that can be coded and tested independently.*
