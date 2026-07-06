# micron — Development Plan

**Last Updated:** 2026-07-06  
**Status:** Active development — core agent working, Phase 1 complete

---

## 🎯 Current State

| Component | Status | Notes |
|-----------|--------|-------|
| CLI | ✅ Working | query, interactive, tools, memory, server |
| 11 Tools | ✅ Working | web_search, fetch_url, read/write_file, list_files, run_command, calculate, python_eval, current_time, save_memory, search_memory, write_knowledge |
| Text-based tool calling | ✅ Working | Parses MiniCPM's `name="tool"> name="param">value` format |
| Firecrawl web search | ✅ Working | Via localhost:3002 |
| Workdir support | ✅ Working | `micron.yaml` + env var override |
| Loop prevention | ✅ Working | `tools_used_this_turn` flag + tool results in history |
| Config system | ✅ Working | `micron.yaml` + CLI + env var priority |
| Tests | ✅ 15 passing | memory, skills, registry |
| save_memory truncation | ✅ FIXED | Parser slices between `name="param">` positions |
| Model output cleanup | ✅ FIXED | Strips `` tags and tool call markup from CLI |
| Knowledge injection | ✅ WORKING | `PromptBuilder._load_knowledge()` reads all `*.md` files (8K char budget) |
| Persona injection | ✅ WORKING | `PromptBuilder._load_persona()` reads `context/persona/*.md` |
| write_knowledge tool | ✅ WORKING | Saves `.md` to `context/knowledge/` with auto-slug |
| Search memory skill | ✅ WORKING | TF-IDF keyword search via `search_memory` |
| Interactive mode UX | 🟡 Needs polish | No chat history display, raw event output |

---

## 📋 Task Plan

### Phase 1: Critical Fixes ✅ COMPLETE

| # | Task | Status |
|---|------|--------|
| 1.1 | Fix save_memory text parser | ✅ DONE |
| 1.2 | Add `search_memory` skill | ✅ DONE |
| 1.3 | Strip `` tags from CLI output | ✅ DONE |
| 1.4 | Verify all tools end-to-end | ✅ DONE |
| 1.5 | Wire knowledge folder into prompt | ✅ DONE |

---

### 🗂️ Knowledge Folder Usage

**Location:** `context/knowledge/` (static markdown files, e.g. `python313.md`)

**Purpose:** Acts like a lightweight, curated Obsidian vault — long-term reference docs, release notes, API specs, project conventions.

**How it works now:**
1. `PromptBuilder._load_knowledge()` reads all `*.md` from `context/knowledge/` at query time
2. Injects as "KNOWLEDGE" section in system prompt (up to 8,000 char budget)
3. Agent can write new documents via `write_knowledge` tool
4. Agent can read/use knowledge files for context-aware answers

**Still planned:**
- Per-query RAG retrieval for large vaults
- Chunking long documents
- Knowledge `search_knowledge` tool for explicit lookups

---

### Phase 2: Core UX

| # | Task | Est. | Status |
|---|------|------|--------|
| 2.1 | Knowledge RAG (query-aware injection) | 2h | ✅ DONE |
| 2.2 | Interactive mode polish (slash cmds + history) | | 1h | ✅ DONE |
| 2.3 | Better error messages for tool failures | 1h | ✅ DONE |
| 2.4 | Add `search_knowledge` tool for explicit doc lookup | 1h | ⏳ |
| 2.5 | Wire `write_knowledge` confirmation flow in CLI | 30m | ⏳ |

#### 2.1 Knowledge RAG improvements
**Current:** All knowledge files injected into every prompt (flat, up to 8K chars).  
**Goal:** For large vaults, retrieve only relevant docs per query using TF-IDF or embedding similarity.

**Options:**
- A: TF-IDF search across knowledge files (like `search_memory`)
- B: Simple keyword filter — only inject files matching query terms
- C: Full embedding-based RAG (heavy)

#### 2.2 Interactive mode polish
**Current:** `run_interactive` reads input, calls `run_query`, loops. No history shown.  
**Goal:** Show conversation history, optionally support multi-turn context.

#### 2.3 Better error messages
**Current:** Tool errors show raw Python exceptions.  
**Goal:** User-friendly messages like "Web search failed: timeout connecting to localhost:3002".

#### 2.4 search_knowledge tool
**Current:** No way to explicitly search knowledge documents. Agent relies on them being injected into prompt.  
**Goal:** `search_knowledge(query)` that finds relevant knowledge docs.

#### 2.5 write_knowledge confirmation
**Current:** Write tools show warning but CLI needs explicit confirmation handling.  
**Goal:** Prompt user "Write this to knowledge? [y/N]" for write tools.

---

### Phase 3: Integration & Polish

| # | Task | Est. | Status |
|---|------|------|--------|
| 3.1 | Server mode integration tests | 2h | ✅ DONE |
| 3.2 | GPU offload config (`n_gpu_layers`) | 1h | ✅ DONE |
| 3.3 | Streaming output cleanup | 1h | ✅ DONE |
| 3.4 | Documentation updates | 1h | ⏳ |

---

### Phase 4: Optional / Nice-to-Have

| # | Task | Est. | Status |
|---|------|------|--------|
| 4.1 | Ollama provider with native tool calling | 4h | 💤 |
| 4.2 | Conversation history persistence | 2h | 💤 |
| 4.3 | Web UI for chat | 8h | 💤 |
| 4.4 | Plugin system for custom tools | 4h | 💤 |

---

## 🧪 Test Checklist

```bash
# Unit tests
python -m pytest tests/ -v

# Tool smoke tests
python -m micron "What time is it?"                    # current_time
python -m micron "Calculate 15 * 23"                   # calculate
python -m micron "Search for Python 3.13"              # web_search
python -m micron "List files in kanban_planner"        # list_files (workdir)
python -m micron "Remember user likes cats"            # save_memory
python -m micron "What did I say about cats?"          # search_memory
python -m micron "Write a guide about Flask setup"     # write_knowledge

# Server
python -m micron --server &
curl -X POST localhost:8000/chat -d '{"message":"hi"}'
```

---

## 🔗 Dependencies

```
Phase 1 (complete)
    → Phase 2.1 (knowledge RAG depends on existing knowledge injection — done in 1.5)
    → Phase 2.2 (interactive polish — standalone)
    → Phase 2.3 (error messages — standalone)
        → Phase 3 (integration depends on stable core)
```

---

## 📦 Model Notes

- **Current:** MiniCPM5-1B-Q8_0 (1.1 GB, via llama.cpp)
- **Config:** `micron.yaml` → `model: models/MiniCPM5-1B-Q8_0.gguf`
- **GPU offload:** `n_gpu_layers: 0` (CPU only) — add to config for GPU
- **Temperature:** 0.1 (deterministic for tool calling)

---

*Update this file after completing each task. Move ✅ to Done column.*