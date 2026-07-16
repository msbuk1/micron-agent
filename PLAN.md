# Micron Agent - Development Plan

**Last Updated:** 2026-07-13  
**Status:** Active Development  
**Repository:** msbuk1/micron-agent  
**Branch:** master

---

## Executive Summary

The micron agent is a **minimal, file-based AI agent** with Obsidian-style memory, Markdown skills, knowledge vault, and tool calling. The codebase is **production-ready** with 88 tests passing.

### Current State

| Metric | Status |
|--------|--------|
| **Test Coverage** | 88/88 passing (100%) ✅ |
| **Core Features** | 100% complete ✅ |
| **Security** | Hardened (30+ command patterns blocked) ✅ |
| **Error Handling** | Standardized across all tools ✅ |
| **Resource Limits** | Added (CPU, memory, processes, files) ✅ |
| **Confirmation Flow** | Working (human-in-the-loop) ✅ |
| **Server** | Merged (rate limiting + auth) ✅ |

---

## Repository Structure

```
micron/
├── micron/
│   ├── __init__.py          # Package exports
│   ├── __main__.py          # CLI entry point
│   ├── agent.py             # Core agent loop + tool calling
│   ├── config.py            # Configuration management
│   ├── llm.py               # LLM backends (llama.cpp, Ollama, OpenAI)
│   ├── memory.py            # JSONL memory + TF-IDF search
│   ├── prompt.py            # Prompt builder
│   ├── sessions.py          # Session persistence
│   ├── skills.py            # Skill loader + plugin integration
│   ├── server.py            # FastAPI + SSE server + web UI + rate limiting + auth
│   ├── plugins/
│   │   └── loader.py        # Plugin discovery
│   └── tools/
│       ├── __init__.py
│       ├── builtin.py       # 17 built-in tools
│       ├── error_handling.py # Standardized error handling
│       └── registry.py      # Tool registry
├── context/
│   ├── skills/              # Markdown skill definitions
│   ├── knowledge/           # Reference documents
│   ├── memory/              # Long-term memory (JSONL)
│   ├── sessions/            # Conversation logs
│   ├── persona/             # Personality layers
│   ├── plugins/             # Python plugin tools
│   └── uploads/             # Uploaded files
├── tests/                   # 88 tests
├── docs/
│   └── self-assembling-skills.md
├── micron.yaml              # Provider configuration
├── pyproject.toml           # Project metadata
└── README.md                # User documentation
```

---

## Feature Inventory

### Core Capabilities ✅

| Feature | Status | Notes |
|---------|--------|-------|
| File-based memory | ✅ Working | JSONL storage, TF-IDF search |
| Markdown skills | ✅ Working | YAML frontmatter, auto-discovery |
| Knowledge vault | ✅ Working | Auto-injected by relevance |
| Composable personas | ✅ Working | Layered personality files |
| Python plugins | ✅ Working | `@tool` decorator, auto-discovery |
| Tool calling | ✅ Working | 17 built-in + plugins |
| Multi-provider | ✅ Working | llama.cpp, Ollama, OpenAI, LM Studio |
| Session persistence | ✅ Working | Auto-logs to `context/sessions/` |
| Web UI | ✅ Working | Dark-themed, SSE streaming |
| File upload | ✅ Working | POST /upload endpoint |
| Security | ✅ Hardened | Blocklists, path traversal guards |
| Interactive CLI | ✅ Working | 15 slash commands |
| Rate limiting | ✅ Working | Configurable per-minute limits |
| Authentication | ✅ Working | API key via header or env var |

### Built-in Tools (17)

| Tool | Write? | Status |
|------|--------|--------|
| `web_search` | No | ✅ |
| `fetch_url` | No | ✅ |
| `read_file` | No | ✅ |
| `write_file` | ✅ | ✅ |
| `list_files` | No | ✅ |
| `run_command` | ✅ | ✅ (with resource limits) |
| `calculate` | No | ✅ |
| `python_eval` | ✅ | ✅ (sandboxed) |
| `current_time` | No | ✅ |
| `save_memory` | No | ✅ |
| `search_memory` | No | ✅ |
| `search_knowledge` | No | ✅ |
| `write_knowledge` | ✅ | ✅ |
| `create_skill` | No | ✅ |
| `search_skill_library` | No | ✅ |
| `delete_file` | ✅ | ✅ |
| `edit_file` | ✅ | ✅ |
| `list_skills` | No | ✅ |

---

## Completed Work

### ✅ Phase 1: Critical Fixes (COMPLETE)

| Task | Status |
|------|--------|
| Fix hardcoded IP address | ✅ Done |
| Add comprehensive .gitignore | ✅ Done |
| Fix TF-IDF bug in search_knowledge | ✅ Done |
| Create unified config system | ✅ Done |
| Fix test_write_tool_requires_confirmation | ✅ Done |

### ✅ Phase 2: Core UX (COMPLETE)

| Task | Status |
|------|--------|
| Knowledge RAG | ✅ Done |
| Interactive mode polish | ✅ Done |
| Better error messages | ✅ Done |
| Add search_knowledge tool | ✅ Done |
| Wire write_knowledge confirmation | ✅ Done |

### ✅ Phase 3: Integration & Polish (COMPLETE)

| Task | Status |
|------|--------|
| Server mode integration tests | ✅ Done |
| GPU offload config | ✅ Done |
| Streaming output cleanup | ✅ Done |
| Documentation updates | ✅ Done |

### ✅ Phase 4: Production Readiness (COMPLETE)

| Task | Status |
|------|--------|
| Add 3 missing tools | ✅ Done |
| Standardize error handling | ✅ Done |
| Enhance security (30+ patterns) | ✅ Done |
| Add resource limits | ✅ Done |
| Human-in-the-loop confirmation | ✅ Done |
| Rate limiting & authentication | ✅ Done |
| Merge server files | ✅ Done |
| Expand test coverage to 66 tests | ✅ Done |

### ✅ Phase 5: Code Quality (COMPLETE)

| Task | Commit | Status |
|------|--------|--------|
| Remove duplicate check_authentication | cb6bfd1 | ✅ Done |
| Fix edit_file silent no-op | cb6bfd1 | ✅ Done |
| Fix run_command return type | cb6bfd1 | ✅ Done |
| Add delete_file directory guard | cb6bfd1 | ✅ Done |
| Cache config in health endpoint | cb6bfd1 | ✅ Done |
| Security: Replace shell=True | e8639b6 | ✅ Done |
| Add .gitignore cleanup | c1089dc | ✅ Done |
| Fix server tests threading | 1a55bb0 | ✅ Done |
| Implement get_authentication() | 5fddae0 | ✅ Done |
| Add delete_file trash recovery | 826491e | ✅ Done |

---

## Remaining Tasks

### 🔴 Critical Priority (This Week)

#### 1. Security: Replace `shell=True` in `run_command`
**Effort:** 2 hours  
**Impact:** Eliminates command injection risk

**Action Items:**
- [ ] Replace `shell=True` with `shlex.split()` + `shell=False`
- [ ] Update blocklist to work with arg list instead of regex
- [ ] Add tests for injection attempts
- [ ] Verify all safe commands still work

**Files:**
- `micron/tools/builtin.py` (lines 330-350)

**Verification:**
```bash
python -m pytest tests/test_resource_limits.py -v
```

---

#### 2. Add `.gitignore` for uploads and secrets
**Effort:** 30 minutes  
**Impact:** Prevent accidental commits of sensitive data

**Action Items:**
- [ ] Add `context/uploads/` to .gitignore
- [ ] Add `*.pyc`, `__pycache__/` to .gitignore
- [ ] Add `.env` to .gitignore
- [ ] Add `.pytest_cache/` to .gitignore

**Files:**
- `.gitignore` (create or update)

---

### 🟡 High Priority (Next Week)

#### 3. Fix `test_server.py` threading errors
**Effort:** 3 hours  
**Impact:** 11 server tests currently skip in sandbox

**Action Items:**
- [ ] Switch from `TestClient` to `httpx.AsyncClient`
- [ ] Add `pytest-asyncio` dependency
- [ ] Rewrite server tests with async fixtures
- [ ] Verify all 77 tests pass (66 + 11 server)

**Files:**
- `tests/test_server.py`

---

#### 4. Implement `get_authentication()` on Config
**Effort:** 1 hour  
**Impact:** Clean up dead auth code

**Action Items:**
- [ ] Add `get_authentication()` method to Config class
- [ ] Or remove dead auth code from server.py
- [ ] Add config defaults for auth settings

**Files:**
- `micron/config.py`

---

#### 5. Add undo/backup for `delete_file`
**Effort:** 2 hours  
**Impact:** Data recovery for accidental deletions

**Action Items:**
- [ ] Create `.trash/` directory in workdir
- [ ] Move deleted files to `.trash/` with timestamp
- [ ] Add `/trash` slash command to list deleted files
- [ ] Add `/restore` slash command to recover files

**Files:**
- `micron/tools/builtin.py` (delete_file function)
- `micron/__main__.py` (new slash commands)

---

#### 6. Add undo for `edit_file`
**Effort:** 1 hour  
**Impact:** Easy revert for bad edits

**Action Items:**
- [ ] Write `.bak` files before edits
- [ ] Auto-cleanup `.bak` files older than 7 days
- [ ] Add `/undo` slash command

**Files:**
- `micron/tools/builtin.py` (edit_file function)
- `micron/__main__.py` (new slash command)

---

### 🟢 Medium Priority (Month 1)

#### 7. Consolidate TF-IDF logic
**Effort:** 2 hours  
**Impact:** Remove code duplication

**Action Items:**
- [ ] Extract shared TF-IDF logic from memory.py
- [ ] Create `micron/search.py` utility module
- [ ] Refactor `search_knowledge` to use shared module
- [ ] Refactor `Memory` class to use shared module

**Files:**
- `micron/search.py` (new)
- `micron/memory.py`
- `micron/tools/builtin.py`

---

#### 8. Add `paste_file` tool
**Effort:** 1 hour  
**Impact:** Quick content upload without web UI

**Action Items:**
- [ ] Create `paste_file(content, filename)` tool
- [ ] Auto-generate filename if not provided
- [ ] Support multiline content
- [ ] Add to TOOLS dict

**Files:**
- `micron/tools/builtin.py`

---

#### 9. Add `patch_file` tool
**Effort:** 2 hours  
**Impact:** Surgical file edits instead of full rewrites

**Action Items:**
- [ ] Create `patch_file(path, old, new)` tool
- [ ] Support multiple patches in one call
- [ ] Add syntax validation for Python files
- [ ] Add to TOOLS dict

**Files:**
- `micron/tools/builtin.py`

---

#### 10. Add `tree` command
**Effort:** 1 hour  
**Impact:** Better directory visibility

**Action Items:**
- [ ] Add `/tree` slash command
- [ ] Show directory structure with file sizes
- [ ] Support depth limit
- [ ] Support filtering by extension

**Files:**
- `micron/__main__.py`

---

### 💡 Feature Ideas (Month 2+)

#### 11. Plugin hot-reload
**Effort:** 3 hours  
**Impact:** Auto-detect changed plugins

**Action Items:**
- [ ] Watch `context/plugins/` for file changes
- [ ] Auto-reload changed plugins
- [ ] Log reload events

---

#### 12. Multi-modal support (vision)
**Effort:** 5 hours  
**Impact:** Image understanding via OpenAI-compatible backends

**Action Items:**
- [ ] Add image input to chat endpoint
- [ ] Convert images to base64 for API
- [ ] Update web UI for image upload
- [ ] Add vision model detection

---

#### 13. Session export
**Effort:** 2 hours  
**Impact:** Share conversations as Markdown/PDF

**Action Items:**
- [ ] Add `/export` slash command
- [ ] Export as Markdown with timestamps
- [ ] Export as PDF (optional)
- [ ] Include tool calls and results

---

#### 14. Rate limiting per-provider
**Effort:** 2 hours  
**Impact:** Different limits for local vs. API providers

**Action Items:**
- [ ] Add provider-specific rate limit config
- [ ] Track requests per provider
- [ ] Apply appropriate limits

---

## Configuration

### Resource Limits
```bash
# Environment variables
MICRON_CMD_MAX_CPU=60              # CPU time in seconds
MICRON_CMD_MAX_MEMORY_MB=512      # Memory in MB
MICRON_CMD_MAX_PROCESSES=50       # Max processes
MICRON_CMD_MAX_FILES=100          # Max open files
```

### Rate Limiting
```yaml
# micron.yaml
rate_limits:
  enabled: false
  chat_requests_per_minute: 60
```

### Authentication
```yaml
# micron.yaml
authentication:
  enabled: false
  api_key_required: false
  api_key_env_var: MICRON_API_KEY
```

### Existing Configuration
```yaml
# micron.yaml
default_provider: lmstudio
providers:
  lmstudio:
    base_url: http://localhost:1234/v1
  openrouter:
    api_key: <your-key>
    base_url: https://openrouter.ai/api/v1
```

---

## Verification Commands

### Run Tests
```bash
python -m pytest tests/ -v  # All 66 tests
```

### Test Resource Limits
```bash
MICRON_CMD_MAX_CPU=5 python -c "from micron.tools.builtin import run_command; print(run_command('sleep 10'))"
# Should timeout after 5 seconds
```

### Test Confirmation Flow
```bash
python -m micron -i
> delete test.txt
# Prompts: Proceed? [Y/n]
```

### Test Rate Limiting
```bash
# Enable rate limiting in micron.yaml, then:
for i in {1..70}; do curl -s http://localhost:8000/health; done
# Should get 429 after 60 requests
```

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Test Coverage | 88/88 (100%) ✅ | 95+ (include server tests) |
| Feature Completeness | 100% | 100% |
| Production Readiness | ✅ Ready | ✅ Ready |
| Security Score | ✅ Excellent (shell=False) | ✅ Excellent |

---

## Next Steps

### Immediate (This Week)
1. Add edit_file undo (Slice 14)

### Short-term (Next Week)
1. Consolidate TF-IDF logic (Slice 15)
2. Add paste_file tool (Slice 16)

### Long-term (Month 2+)
1. Add patch_file tool (Slice 17)
2. Add tree command (Slice 18)
3. Plugin hot-reload
4. Multi-modal support
5. Session export

---

*This plan consolidates completed work and new priorities from codebase review.*
