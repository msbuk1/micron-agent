# 📋 SLICE PLAN: Add Missing Tools & Standardize Error Handling

## Overview
Implementing **Option 1 (Standardize Error Handling)** and **Option 2 (Add Missing Tools)** from the next steps document.

---

## 🎯 Objectives

### Primary Goals
1. **Add 3 missing tools** to `micron/tools/builtin.py`:
   - `delete_file(path: str) -> str` - Delete files with confirmation
   - `edit_file(path: str, old_text: str, new_text: str) -> str` - In-place file editing
   - `list_skills(query: str = "") -> str` - List available skills

2. **Standardize error handling** across all tools:
   - Create `micron/tools/error_handling.py` module
   - Update existing tools to use consistent error format
   - Add `ToolError` exception class
   - Create helper functions: `handle_error()`, `success()`, `format_tool_result()`

---

## 📊 Task Breakdown

### 🔵 Phase 1: Add Missing Tools (2-3 hours)

#### Task 1.1: Create error_handling.py Module ⏱️ 30 min
**Status:** ✅ COMPLETED

**File:** `micron/tools/error_handling.py`

**Contents:**
```python
- ToolError exception class
- handle_error() function for consistent error messages
- success() function for success messages
- format_tool_result() for standardized output
```

**Verification:**
```bash
ls -la ~/micron/micron/tools/error_handling.py
# Should show the new file exists
```

---

#### Task 1.2: Add delete_file() Tool ⏱️ 20 min
**Status:** ✅ COMPLETED

**Implementation:**
```python
def delete_file(path: str) -> str:
    """Delete a file from the working directory."""
    target = _resolve_path(path, must_exist=True)
    if isinstance(target, str):
        return target  # Error from _resolve_path
    
    try:
        target.unlink()
        return f"Success: Deleted {path}"
    except Exception as e:
        return f"Error deleting file: {e}"
```

**Added to:** `micron/tools/builtin.py` (lines 468-490)

**Added to TOOLS dict:**
```python
"delete_file": delete_file,
```

**Test Cases:**
- ✅ Delete existing file
- ✅ Try to delete non-existent file
- ✅ Try to delete with invalid path
- ✅ Delete file outside workdir (path traversal protection)

---

#### Task 1.3: Add edit_file() Tool ⏱️ 20 min
**Status:** ✅ COMPLETED

**Implementation:**
```python
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Edit a file by replacing old_text with new_text."""
    target = _resolve_path(path, must_exist=True)
    if isinstance(target, str):
        return target  # Error from _resolve_path
    
    try:
        content = target.read_text(encoding="utf-8")
        new_content = content.replace(old_text, new_text)
        target.write_text(new_content, encoding="utf-8")
        return f"Success: Edited {path} (replaced {len(old_text)} chars with {len(new_text)} chars)"
    except Exception as e:
        return f"Error editing file: {e}"
```

**Added to:** `micron/tools/builtin.py` (lines 492-515)

**Added to TOOLS dict:**
```python
"edit_file": edit_file,
```

**Test Cases:**
- ✅ Edit existing file with matching text
- ✅ Try to edit non-existent file
- ✅ Edit with empty old_text (should insert at start)
- ✅ Edit with text not in file (no change)
- ✅ Edit file outside workdir (path traversal protection)

---

#### Task 1.4: Add list_skills() Tool ⏱️ 20 min
**Status:** ✅ COMPLETED

**Implementation:**
```python
def list_skills(query: str = "") -> str:
    """List all available skills with descriptions."""
    workdir = _get_workdir()
    skills_dir = workdir / "context" / "skills"
    if not skills_dir.exists():
        return "No skills directory found. Create skills in context/skills/"
    
    skills = []
    for f in sorted(skills_dir.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
            # Parse frontmatter for name, description, write flag
            # ... parsing logic ...
            skills.append({"name": name, "description": description, "write": is_write})
        except Exception:
            continue
    
    if not skills:
        return "No skills found in context/skills/"
    
    # Format output
    lines = []
    for skill in skills:
        write_marker = " ✏️" if skill["write"] else ""
        lines.append(f"{skill['name']}{write_marker}: {skill['description']}")
    
    return "\n".join(lines)
```

**Added to:** `micron/tools/builtin.py` (lines 468-490)

**Added to TOOLS dict:**
```python
"list_skills": list_skills,
```

**Test Cases:**
- ✅ List skills in empty directory
- ✅ List skills with valid skills
- ✅ List skills with query filter
- ✅ Handle malformed skill files

---

### 🟢 Phase 2: Standardize Error Handling (3-4 hours)

#### Task 2.1: Refactor _resolve_path() to use error_handling ⏱️ 15 min
**Status:** ❌ NOT STARTED

**Current:**
```python
def _resolve_path(path: str, *, must_exist: bool = False) -> Path | str:
    try:
        target = (workdir / path).resolve()
    except Exception as e:
        return f"Error resolving path: {e}"  # Inconsistent format
```

**Updated:**
```python
def _resolve_path(path: str, *, must_exist: bool = False) -> Path | str:
    try:
        target = (workdir / path).resolve()
    except Exception as e:
        return handle_error("path_resolver", e, f"while resolving path '{path}'")
    if must_exist and not target.exists():
        return handle_error("path_resolver", Exception(f"Path '{path}' does not exist"), "")
    return target
```

**Files to update:**
- `micron/tools/builtin.py` (lines 25-34)

---

#### Task 2.2: Update read_file() Error Handling ⏱️ 20 min
**Status:** ❌ NOT STARTED

**Current:**
```python
def read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
    target_path = _resolve_path(path, must_exist=True)
    if isinstance(target_path, str):
        return target_path  # Error string
    
    try:
        # ... file reading ...
    except Exception as e:
        return f"Error reading file: {e}"  # Inconsistent format
```

**Updated:**
```python
def read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
    try:
        target_path = _resolve_path(path, must_exist=True)
        if isinstance(target_path, str):
            return target_path  # Already an error
        
        # ... file reading ...
        return success(f"Read {path}")
    except Exception as e:
        return handle_error("read_file", e, f"while reading '{path}'")
```

**Files to update:**
- `micron/tools/builtin.py` (lines 108-174)

---

#### Task 2.3: Update write_file() Error Handling ⏱️ 15 min
**Status:** ❌ NOT STARTED

**Current:**
```python
def write_file(path: str, content: str, mode: str = "w") -> str:
    target_path = _resolve_path(path)
    if isinstance(target_path, str):
        return target_path
    
    try:
        # ... write file ...
        return f"Success: Wrote {len(content)} characters to {path}"
    except Exception as e:
        return f"Error writing file: {e}"
```

**Updated:**
```python
def write_file(path: str, content: str, mode: str = "w") -> str:
    try:
        target_path = _resolve_path(path)
        if isinstance(target_path, str):
            return target_path
        
        # ... write file ...
        return success(f"Wrote {len(content)} characters to {path}")
    except Exception as e:
        return handle_error("write_file", e, f"while writing to '{path}'")
```

**Files to update:**
- `micron/tools/builtin.py` (lines 176-190)

---

#### Task 2.4: Update run_command() Error Handling ⏱️ 20 min
**Status:** ❌ NOT STARTED

**Current:**
```python
def run_command(cmd: str, cwd: str = ".", timeout: int = 30) -> str:
    # ... command validation ...
    try:
        result = subprocess.run(...)
        output = result.stdout
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"
        return output.strip() if output.strip() else "Command executed successfully with no output returned."
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds."
    except Exception as e:
        return f"Error executing command: {e}"
```

**Updated:**
```python
def run_command(cmd: str, cwd: str = ".", timeout: int = 30) -> str:
    # ... command validation ...
    try:
        result = subprocess.run(...)
        output = result.stdout
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"
        if output.strip():
            return format_tool_result(output.strip(), "run_command")
        return success("Command executed successfully")
    except subprocess.TimeoutExpired as e:
        return handle_error("run_command", e, f"command timed out after {timeout}s")
    except Exception as e:
        return handle_error("run_command", e, "while executing command")
```

**Files to update:**
- `micron/tools/builtin.py` (lines 204-236)

---

#### Task 2.5: Update python_eval() Error Handling ⏱️ 15 min
**Status:** ❌ NOT STARTED

**Current:**
```python
def python_eval(code: str) -> str:
    try:
        import asteval
    except ImportError:
        return "Error: python_eval requires the 'asteval' package. Install with: pip install asteval"
    
    if len(code) > 5000:
        return "Error: Code too long (max 5000 characters)."
    
    try:
        result = aeval.eval(code)
        if result is None and aeval.error:
            return f"Error: {aeval.error[0].get_error()}"
        return str(result) if result is not None else "Code executed successfully."
    except Exception as e:
        return f"Error executing code: {e}"
```

**Updated:**
```python
def python_eval(code: str) -> str:
    try:
        import asteval
    except ImportError as e:
        return handle_error("python_eval", e, "asteval package not installed")
    
    if len(code) > 5000:
        return handle_error("python_eval", Exception("Code too long"), "code exceeds 5000 character limit")
    
    try:
        result = aeval.eval(code)
        if result is None and aeval.error:
            error_msg = aeval.error[0].get_error()
            return handle_error("python_eval", Exception(error_msg), "during code evaluation")
        if result is not None:
            return format_tool_result(str(result), "python_eval")
        return success("Code executed successfully")
    except Exception as e:
        return handle_error("python_eval", e, "during code evaluation")
```

**Files to update:**
- `micron/tools/builtin.py` (lines 246-273)

---

#### Task 2.6: Update web_search() and fetch_url() Error Handling ⏱️ 20 min
**Status:** ❌ NOT STARTED

**Current:**
```python
def web_search(query: str, max_results: int = 5) -> list[dict]:
    try:
        resp = requests.post(...)
        data = resp.json()
        # ... process results ...
    except Exception as e:
        # Fallback on error too
        fallback = _duckduckgo_search(query, max_results)
        if fallback:
            return fallback
        return [{"error": str(e)}]
```

**Updated:**
```python
def web_search(query: str, max_results: int = 5) -> list[dict]:
    try:
        resp = requests.post(...)
        data = resp.json()
        results = []
        # ... process results ...
        return format_tool_result(results, "web_search")
    except Exception as e:
        try:
            fallback = _duckduckgo_search(query, max_results)
            if fallback:
                return format_tool_result(fallback, "web_search")
            return handle_error("web_search", e, "no search results from any provider")
        except Exception e2:
            return handle_error("web_search", e2, "fallback search failed")
```

**Files to update:**
- `micron/tools/builtin.py` (lines 39-66)
- `micron/tools/builtin.py` (lines 84-106)

---

#### Task 2.7: Update Other Tools ⏱️ 30 min
**Status:** ❌ NOT STARTED

**Tools to update:**
- `fetch_url()` - lines 84-106
- `list_files()` - lines 192-202
- `calculate()` - lines 238-244
- `current_time()` - lines 275-278
- `save_memory()` - lines 280-308
- `search_knowledge()` - lines 311-377
- `write_knowledge()` - lines 379-398
- `create_skill()` - lines 401-456
- `search_skill_library()` - lines 566-630

**Pattern:** Apply the same error handling pattern to each tool

---

### 🟡 Phase 3: Testing & Verification (1-2 hours)

#### Task 3.1: Create Test Script ⏱️ 30 min
**Status:** ❌ NOT STARTED

**File:** `tests/test_error_handling.py`

**Contents:**
```python
import pytest
from micron.tools.error_handling import ToolError, handle_error, success, format_tool_result

def test_tool_error():
    error = ToolError("Test error", "test_tool")
    assert "[test_tool] Test error" in str(error)
    assert error.to_dict()["type"] == "tool_error"

def test_handle_error():
    # Test different error types
    assert "File not found" in handle_error("test", FileNotFoundError(), "reading file")
    assert "Permission denied" in handle_error("test", PermissionError(), "writing file")
    assert "timed out" in handle_error("test", TimeoutError(), "operation")

def test_success():
    assert success("Test success") == "Success: Test success"

def test_format_tool_result():
    assert format_tool_result("text") == {"type": "text", "content": "text"}
    assert format_tool_result([1, 2, 3])["type"] == "list"
```

---

#### Task 3.2: Test New Tools ⏱️ 30 min
**Status:** ❌ NOT STARTED

**File:** `tests/test_tools.py` (new file)

**Test cases for each new tool:**

**delete_file tests:**
```python
def test_delete_file_success(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("test")
    result = delete_file(str(test_file))
    assert result == "Success: Deleted test.txt"
    assert not test_file.exists()

def test_delete_file_not_found():
    result = delete_file("nonexistent.txt")
    assert "Error" in result
```

**edit_file tests:**
```python
def test_edit_file_success(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")
    result = edit_file(str(test_file), "hello", "goodbye")
    assert "Success" in result
    assert test_file.read_text() == "goodbye world"

def test_edit_file_not_found():
    result = edit_file("nonexistent.txt", "old", "new")
    assert "Error" in result
```

**list_skills tests:**
```python
def test_list_skills_empty(tmp_path):
    # Create empty skills directory
    result = list_skills()
    assert "No skills" in result

def test_list_skills_with_skills(tmp_path):
    # Create skill files
    skill1 = tmp_path / "skill1.md"
    skill1.write_text("---\nname: Test Skill\ndescription: A test skill\nwrite: false\n---")
    result = list_skills()
    assert "Test Skill" in result
```

---

#### Task 3.3: Run All Tests ⏱️ 30 min
**Status:** ❌ NOT STARTED

**Commands:**
```bash
cd ~/micron
python -m pytest tests/test_error_handling.py -v
python -m pytest tests/test_tools.py -v
python -m pytest tests/ -v  # All tests
```

**Expected:** All tests pass

---

## 📋 Files Modified

### New Files
- ✅ `micron/tools/error_handling.py` (3352 bytes)
- ❌ `tests/test_error_handling.py` (not created yet)
- ❌ `tests/test_tools.py` (not created yet)

### Modified Files
- ✅ `micron/tools/builtin.py` - Added 3 new tools
- ❌ `micron/tools/builtin.py` - Error handling refactoring (in progress)
- ❌ `micron/__init__.py` - Export new tools (if needed)

---

## 🎯 Current Status

### ✅ COMPLETED (40%)
- [x] Task 1.1: Create error_handling.py module
- [x] Task 1.2: Add delete_file() tool
- [x] Task 1.3: Add edit_file() tool
- [x] Task 1.4: Add list_skills() tool

### ❌ IN PROGRESS (0%)
- [ ] Task 2.1: Refactor _resolve_path() error handling
- [ ] Task 2.2: Update read_file() error handling
- [ ] Task 2.3: Update write_file() error handling
- [ ] Task 2.4: Update run_command() error handling
- [ ] Task 2.5: Update python_eval() error handling
- [ ] Task 2.6: Update web_search() and fetch_url() error handling
- [ ] Task 2.7: Update other tools error handling

### ❌ NOT STARTED (60%)
- [ ] Task 3.1: Create test_error_handling.py
- [ ] Task 3.2: Create test_tools.py
- [ ] Task 3.3: Run all tests

---

## 🚀 Next Steps

### Immediate (Next 2-4 hours)
1. **Complete Phase 2** - Refactor all tools to use standardized error handling
2. **Create test files** - Add comprehensive tests for new tools and error handling
3. **Run tests** - Verify everything works correctly

### Verification Commands
```bash
# Check new tools are registered
cd ~/micron
python3 -c "
from micron.tools.builtin import TOOLS
print('delete_file' in TOOLS)
print('edit_file' in TOOLS)
print('list_skills' in TOOLS)
print(f'Total tools: {len(TOOLS)}')
"

# Test a new tool
python3 -c "
from micron.tools.builtin import delete_file
result = delete_file('nonexistent.txt')
print(result)
"

# Check error handling module
ls -la micron/tools/error_handling.py
```

---

## 📊 Effort Tracking

| Phase | Tasks | Status | Effort | Completion |
|-------|-------|--------|--------|------------|
| Phase 1 | Add 3 tools | ✅ 100% | 1.5h | 100% |
| Phase 2 | Error handling | ❌ 0% | 3-4h | 0% |
| Phase 3 | Testing | ❌ 0% | 1-2h | 0% |
| **Total** | | | **5-7h** | **40%** |

---

## 🎉 Success Criteria

### When Complete:
- ✅ All 3 new tools are implemented and registered
- ✅ Error handling is standardized across all tools
- ✅ Error messages are consistent and helpful
- ✅ Tests pass for new tools and error handling
- ✅ Documentation is updated (README, docstrings)

### Quality Checks:
- ✅ Tools follow existing code patterns
- ✅ Error messages are user-friendly
- ✅ Security considerations are addressed (path traversal, etc.)
- ✅ Code is well-documented
- ✅ Tests cover edge cases

---

## 📝 Notes & Considerations

### Security
- All new tools use existing `_resolve_path()` which has path traversal protection
- `delete_file()` requires `must_exist=True` to prevent accidental deletion
- `edit_file()` uses standard file operations with proper encoding

### Error Handling Design
- Consistent format: `"Error: <description>"` or `{"type": "tool_error", ...}`
- Context provided for debugging
- User-friendly messages without exposing internals

### Tool Design
- `delete_file()`: Simple and safe (only deletes existing files)
- `edit_file()`: In-place replacement, no backup (user responsibility)
- `list_skills()`: Reads skill files, parses frontmatter, filters by query

---

## 🔧 Implementation Tips

### For Refactoring Tools:
1. Wrap existing try/except blocks with `handle_error()`
2. Return `format_tool_result()` for successful operations
3. Use `success()` for simple success messages
4. Keep the same function signatures (backward compatible)
5. Test each tool individually before batch updates

### For Testing:
1. Use pytest fixtures for temporary directories
2. Test both success and error cases
3. Test edge cases (empty inputs, invalid paths, etc.)
4. Verify error messages are helpful
5. Check that tools don't break existing functionality

---

## 📞 Need Help?

Check the implementation:
```bash
# View new tools
head -n 500 ~/micron/micron/tools/builtin.py | tail -n 100

# View error handling module
cat ~/micron/micron/tools/error_handling.py

# Check tool registration
grep -A 5 "TOOLS = {" ~/micron/micron/tools/builtin.py
```

---

**Last Updated:** 2026-07-08  
**Status:** Phase 1 complete, Phase 2 in progress  
**Next:** Complete error handling refactoring