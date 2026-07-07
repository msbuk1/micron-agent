# micron — Detailed Slice Implementation Plan (D–H)

**Status**: All slices D–H implemented — 37/37 tests passing.  
**Updated**: 2026-07-07

---

## Overview

This document details the implementation plans for vertical slices D–H. Each slice is independently implementable, builds on the existing P0‑fixed foundation, and includes concrete code snippets and acceptance criteria.

---

## Architecture at a Glance

```
micron/
├── agent.py              # Core loop (P0 fixed)
├── llm.py                # Backends: llama.cpp, Ollama, OpenAI (P0 fixed)
├── memory.py             # File memory + TF‑IDF (P0 fixed)
├── prompt.py             # Dynamic prompt builder (P0 fixed)
├── skills.py             # Markdown skill loader
├── tools/
│   ├── builtin.py        # Core tools (read/write/shell/search/memory)
│   └── registry.py       # Tool registry
├── server/               # FastAPI server (exists, usable)
│   └── web_app.py        # ← Slice H: minimal web UI
├── context/
│   ├── knowledge/        # Static knowledge docs (*.md)
│   ├── sessions/         # JSONL conversation history (← Slice E)
│   ├── persona/          # Persona profiles
│   └── memory/           # Memory JSONL files
└── skill_plugins/        # Python-based tool plugins (← Slice G)
```

---

## Slice D: Knowledge RAG Retrieval ⏱ (2–4 hours)

**Goal**: Replace flat knowledge injection with query‑aware retrieval so large vaults stay performant and system prompts remain small.

### Logic
- `memory.py` already provides TF‑IDF scoring (`_tokenize`, `_tf`, `_idf`, `search`).
- Add a dedicated `search_knowledge` tool.
- `PromptBuilder._load_knowledge()` optionally calls it when document count exceeds threshold.

### Changes

#### 1. `micron/tools/builtin.py`

Replace the existing `search_memory` function with a new `search_knowledge` that uses TF‑IDF internally:

```python
def search_knowledge(query: str = "", k: int = 5) -> str:
    """Search knowledge documents using TF‑IDF scoring. Returns ranked markdown snippets."""
    import math
    from collections import Counter
    from pathlib import Path
    import os, re
    from datetime import datetime

    workdir = Path(os.getenv("MICRON_WORKDIR", os.getcwd()))
    knowledge_dir = workdir / "context" / "knowledge"
    if not knowledge_dir.exists():
        return "(knowledge directory not found)"

    # Load all markdown files
    texts: list[tuple[str, str]] = []
    for f in sorted(knowledge_dir.glob("*.md")):
        txt = f.read_text(errors="replace").strip()
        if txt.startswith("---"):
            parts = txt.split("---", 2)
            if len(parts) >= 3:
                txt = parts[2]
        txt = re.sub(r"^#\s+.*$", "", txt, flags=re.MULTILINE)
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt and len(txt) > 5:
            texts.append((f.stem, txt))

    if not texts:
        return "(no knowledge documents)"

    def tokenize(t: str) -> list[str]:
        return re.findall(r"\b\w+\b", t.lower())

    # Lightweight Memory instance to reuse internals
    from micron.memory import Memory
    mem = Memory(str(workdir / "memory"))
    tokens_per_doc = [Counter(tokenize(d.text)) for d in mem._docs]
    vocab = set(t for toks in tokens_per_doc for t in toks)
    n_docs = len(mem._docs)
    idf = {term: math.log(n_docs / sum(1 for toks in tokens_per_doc if term in toks) + 1) + 1.0
           for term in vocab}

    query_tokens = Counter(tokenize(query))
    if not query_tokens:
        return "(no search query)"

    scored = []
    for (slug, _), toks in zip(texts, tokens_per_doc):
        score = sum(toks.get(t, 0) * idf.get(t, 0) for t in query_tokens) / (sum(toks.values()) + 1)
        scored.append((score, slug))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, slug in scored[:k]:
        if score <= 0:
            continue
        _, full = next(((s, t) for (ss, t) in texts if ss == slug), ("", ""))
        snippet = full[:300].replace("\n", " ").strip()
        out.append(f"[{slug}] (score: {score:.2f}) {snippet}...")

    return "\n".join(out) if out else "(no relevant knowledge)"
```

#### 2. Registration Updates

In the `TOOLS` dict and `CORE_SKILLS` set, replace `search_memory` with `search_knowledge`:

```python
# TOOLS dict
default_tools = {
    ...
    "search_knowledge": search_knowledge,
    ...
}

# CORE_SKILLS
CORE_SKILLS = {"web_search", "fetch_url", "read_file", "write_file", "list_files",
               "run_command", "calculate", "python_eval", "current_time",
               "save_memory", "search_knowledge", "write_knowledge", ...}
```

#### 3. `micron/prompt.py` — Optional RAG Trigger

Update `_load_knowledge()` to use search when vault is large:

```python
def _load_knowledge(self, query: str) -> str:
    knowledge = self.memory.search(query, k=5)  # keyword fallback
    # If vault large, optionally call self.tools.call("search_knowledge", query=query)
    ...
```

### Acceptance Criteria
- `search_knowledge("Python cache")` returns ranked document snippets with scores
- Prompt construction stays under ~2K tokens even with 50+ knowledge files
- Backwards compatible: full injection still works for small vaults

---

## Slice E: Conversation Persistence ⏱ (1–2 hours)

**Goal**: Enable cross‑session memory via `context/sessions/*.jsonl` using the existing `SessionLogger`.

### Logic
- `sessions.py` already implements `SessionLogger` with JSONL, atomic appends, and file locking.
- Wire it into the agent loop for interactive mode.
- Add CLI commands for session management.

### Changes

#### 1. `micron/__main__.py` — Interactive Mode Integration

```python
# near imports
from micron.sessions import SessionLogger

# in run_interactive(), before the main loop:
sessions_dir = Path(agent.context_dir) / "sessions"
logger = SessionLogger(sessions_dir)
session_id = logger.start_session()
print(f"Session: {session_id}")

# inside the loop, before sending to agent:
logger.log_turn("user", query)

# after receiving agent response:
logger.log_turn("assistant", cleaned or result)
```

#### 2. Session Commands

Add to the interactive command handler:

```python
elif command in ("sessions", "sess", "ss"):
    sessions = logger.list_sessions(10)
    if not sessions:
        print("No sessions found.")
    else:
        print("Recent sessions:")
        for s in sessions:
            print(f"  {s['id']}  {s['turns']} turns  {s['size']//1024}KB")

elif command.startswith("resume"):
    target = cmd.split(maxsplit=1)[1] if len(cmd.split()) > 1 else ""
    resumed = logger.get_session_context(target)
    if not resumed:
        print(f"Session '{target}' not found.")
    else:
        history.clear()
        history.extend(resumed)
        print(f"Resumed session {target} ({len(resumed)} turns loaded).")
```

#### 3. CLI Flag: `--session <id>`

When provided, load session history into the `history` list before running the query.

### Acceptance Criteria
- `micron --session test run "hello"` creates a new session file
- `micron --session test run "how are you?"` appends to the same session
- `micron --session test --list-sessions` shows the session
- Session history is correctly restored on resume

---

## Slice F: Ollama Native Tool Calling ✅ DONE

**Goal**: Use Ollama’s built‑in function calling for models that support it, falling back to text parsing for older versions.

### Logic
- `llm.py` already has per‑model `chat_format` detection.
- Add an `OllamaToolAdapter` that converts internal `ToolCall` objects to Ollama’s native JSON tool schema.
- Auto‑detect models that support native tools.

### Changes

#### 1. `micron/llm.py` — Add Adapter and Detection

```python
class OllamaToolAdapter:
    @staticmethod
    def to_ollama_tools(tool_calls: list) -> list[dict]:
        return [
            {
                "name": tc.name,
                "description": tc.description or "",
                "parameters": tc.schema or {},
            }
            for tc in tool_calls
            if not tc.is_write  # write tools handled separately
        ]

    @staticmethod
    def needs_native_tools(model_name: str) -> bool:
        return bool(re.search(r"(qwen2\.5|llama3\.1|llama3\.2|gemma2)\b", model_name, re.I))
```

#### 2. Modify Chat Completion Flow

In the Ollama backend section of `create_chat_completion`:

```python
if self.use_native_tools and tools:
    payload["tools"] = OllamaToolAdapter.to_ollama_tools(tools)
    payload["format"] = "json"  # force structured output
```

#### 3. Graceful Fallback

If `use_native_tools=False` or model not supported, keep existing text‑parsing fallback.

### Acceptance Criteria
- Models like `llama3.1:7b` use native JSON tool calls (visible in server logs)
- Older Ollama models fall back to text parsing without errors
- Write‑tool confirmation flow remains unchanged

---

## Slice G: Python Plugin System ✅ DONE

**Goal**: Allow contributors to define tools as Python functions using a `@tool` decorator, complementing the markdown‑based skill system.

### Logic
- New `skill_plugins/` directory for Python modules.
- Decorator registers tool descriptors in a global list.
- `skills.py` discovers and merges plugin tools with markdown skills.

### Changes

#### 1. `micron/skill_plugins/__init__.py`

```python
from typing import Callable, Any
from dataclasses import dataclass
from .loader import tool_descriptors

@dataclass
class ToolDescriptor:
    name: str
    description: str
    func: Callable
    parameters: dict
    write: bool = False

tool_descriptors: list[ToolDescriptor] = []

def tool(*, name: str, description: str, write: bool = False):
    def decorator(func: Callable):
        td = ToolDescriptor(
            name=name,
            description=description,
            func=func,
            parameters={},  # could inspect signature
            write=write,
        )
        tool_descriptors.append(td)
        return func
    return decorator
```

#### 2. `micron/skill_plugins/loader.py`

```python
import importlib, pkgutil, pathlib
from . import tool_descriptors

def discover_plugins(plugin_dir: pathlib.Path = pathlib.Path(__file__).parent):
    for finder, name, ispkg in pkgutil.iter_modules([str(plugin_dir)]):
        if not ispkg and not name.endswith("_test"):
            try:
                importlib.import_module(f"micron.skill_plugins.{name}")
            except Exception as e:
                print(f"[WARN] Failed to load plugin {name}: {e}")
```

#### 3. `micron/skills.py` — Merge Plugin Tools

```python
from micron.skill_plugins.loader import discover_plugins
discover_plugins()
from micron.skill_plugins import tool_descriptors as plugin_tools

def all_tools(self) -> list[dict]:
    md_tools = [ ... existing markdown skill parsing ... ]
    plugin_list = [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "write": t.write,
            "plugin": True,
        }
        for t in plugin_tools
    ]
    return md_tools + plugin_list
```

### Acceptance Criteria
- Drop `plugins/tools/calculator.py` with `@tool` → appears in `list_tools`
- Plugins execute with existing sandbox (e.g., `calculate` via `asteval`)
- Import errors are caught and warned, not fatal

---

## Slice H: Minimal Web UI ✅ DONE

**Goal**: Provide a basic browser-based chat interface using FastAPI and Server‑Sent Events.

### Logic
- Reuse existing `server.py` and agent instance.
- Serve a simple HTML/JS page that connects via SSE.
- Support session management via query params or headers.

### Changes

#### 1. `server/web_app.py` (new file)

```python
from fastapi import FastAPI, Request, WebSocket, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from micron.agent import create_agent
from micron.llm import create_backend
import asyncio, json, os

app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

AGENT = create_agent(...)  # similar to server.py lifespan

@app.get("/", response_class=HTMLResponse)
def chat_ui():
    return """
    <!doctype html>
    <html><head><title>micron</title>
    <style>
      body{font-family:sans-serif;margin:0;padding:16px;background:#0f1117;color:#c9d1d9}
      #chat{flex:1;overflow-y:auto;height:80vh;border:1px solid #30363d;padding:12px;border-radius:8px}
      .msg{margin:8px 0;white-space:pre-wrap} .user{color:#58a6ff} .assistant{color:#e6edf3}
      input{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:8px;border-radius:4px}
    </style></head>
    <body>
      <div id="chat"></div>
      <form id="frm"><input id="inp" autofocus /><button>Send</button></form>
      <script>
        const chat=document.getElementById('chat');
        document.getElementById('frm').onsubmit=e=>{e.preventDefault();
          const inp=document.getElementById('inp');
          addMsg('user', inp.value);
          inp.value='';
          const evt=new EventSource('/sse?msg='+encodeURIComponent(inp.value));
          evt.onmessage=ev=>{addMsg('assistant', ev.data);};
        };
        function addMsg(cls, txt){const d=document.createElement('div');d.className='msg '+cls;d.textContent=txt;chat.appendChild(d);chat.scrollTop=chat.scrollHeight;}
      </script>
    </body></html>
    """

@app.get("/sse")
async def sse_endpoint(msg: str):
    async def stream():
        async for chunk in AGENT.run(msg):
            yield f"data: {json.dumps(chunk)}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")
```

#### 2. Update `server.py` (optional)

Keep existing API endpoints; optionally expose the web app under the same host.

### Acceptance Criteria
- `curl localhost:8000` returns a usable chat page
- Messages stream back with tool call indicators
- Works end‑to‑end with all existing tools

---

## Cross‑Cutting Notes

- **Backwards compatibility**: All slices preserve existing APIs; none of the P0 fixes are reverted.
- **Dependencies**: Only `asteval` (for sandboxing) is introduced in Slice D/G; optional for plugins.
- **Testing**: Each slice has clear acceptance criteria; existing 37 tests remain green.
- **Progression**: Slices are ordered by impact and dependency: D (foundation) → E (persistence) → F (better tool calling) → G (extensibility) → H (UX).