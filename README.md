# micron — Lightweight AI Agent

A minimal, file-based AI agent with **Obsidian-style memory**, **Markdown skills**, and **tool calling** — designed to run on 1B models on CPU.

## Features

- 📁 **File-based memory** — JSONL storage, human-editable, git-friendly
- 📚 **Markdown skills** — Drop `.md` files in `context/skills/` with YAML frontmatter
- 🎭 **Composable personas** — Stack `.md` files in `context/persona/` for layered personality
- 🛠️ **Tool calling** — OpenAI-compatible function calling with write-confirmation
- ⚡ **Local-first** — Runs on SmolLM2-1.7B, Qwen2.5-1.5B, Gemma-2-2B via llama.cpp/Ollama
- 🔌 **Extensible** — ~300 lines core, zero framework lock-in

## Quick Start

```bash
# 1. Clone and setup venv
git clone <repo-url> micron && cd micron
python3 -m venv .venv
source .venv/bin/activate

# 2. Install
pip install -e .[dev,server]

# 3. Download a model (SmolLM2-1.7B recommended)
mkdir -p models
wget -O models/smollm2-1.7b-q4_k_m.gguf \
  https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF/resolve/main/smollm2-1.7b-instruct-q4_k_m.gguf

# 4. Run CLI
python -m micron "What's the weather in London?"

# 5. Or start API server
python -m micron --server
```

## Project Structure

```
micron/
├── context/
│   ├── skills/        # Tool definitions (Markdown + YAML frontmatter)
│   ├── knowledge/     # RAG documents (auto-indexed)
│   ├── memory/        # Long-term memory (memory.jsonl)
│   └── persona/       # Personality layers (concatenated)
├── micron/
│   ├── __init__.py
│   ├── __main__.py    # CLI entry point
│   ├── agent.py       # Core agent (~300 lines)
│   ├── memory.py      # JSONL + TF-IDF memory (from agent-memory-lite)
│   ├── skills.py      # Skill loader (Markdown + YAML)
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── builtin.py # Built-in tools (web search, files, calc, code)
│   │   └── registry.py
│   ├── llm.py         # llama.cpp / Ollama / OpenAI backends
│   ├── prompt.py      # Prompt builder
│   └── server.py      # FastAPI + SSE server
├── models/            # GGUF model files (gitignored)
├── tests/
│   ├── test_memory.py
│   ├── test_skills.py
│   └── test_registry.py
├── pyproject.toml
└── README.md
```

## CLI Usage

```bash
# Single query
python -m micron "What is 2+2?"

# Interactive mode
python -m micron -i

# List available tools
python -m micron --list-tools

# List memories
python -m micron --list-memories

# Add a memory
python -m micron --add-memory "User prefers dark mode"

# Search memories
python -m micron --search-memory "dark mode"

# Start server
python -m micron --server

# Provider options
python -m micron --provider ollama --model smollm2:1.7b "Hello"
python -m micron --provider openrouter --model mistralai/mistral-7b-instruct "Hello"
```

## API Server

```bash
# Start server (default: http://localhost:8000)
python -m micron --server

# Endpoints
GET  /health              # Health check
GET  /tools               # List tools
POST /chat                # Chat with agent (SSE stream)
POST /memory              # Add memory
GET  /memory              # List memories
POST /memory/search       # Search memories
DELETE /memory/{id}       # Delete memory
POST /skills/reload       # Reload skills from disk

# Example chat request
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, what can you do?", "stream": false}'
```

## Skills

Skills are Markdown files with YAML frontmatter in `context/skills/`:

```markdown
---
name: web_search
description: Search the web for current information
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query
    max_results:
      type: integer
      default: 5
---

# Implementation in micron/tools/builtin.py
def web_search(query: str, max_results: int = 5) -> list[dict]:
    ...
```

### Built-in Tools

| Tool | Description | Write? |
|------|-------------|--------|
| `web_search` | Search DuckDuckGo | No |
| `fetch_url` | Fetch and extract URL content | No |
| `read_file` | Read file from workspace | No |
| `write_file` | Write file to workspace | Yes |
| `list_files` | List files in directory | No |
| `run_command` | Run shell command | Yes |
| `calculate` | Evaluate math expression | No |
| `python_eval` | Execute Python code | Yes |
| `current_time` | Get current date/time | No |

## Memory

Memory is stored as JSONL in `context/memory/memory.jsonl`:

```json
{"id": "a1b2c3d4e5f6", "timestamp": "2026-01-15T10:30:00+00:00", "text": "User prefers dark mode", "tags": ["preference", "ui"], "importance": 3}
```

Search uses TF-IDF + time-decay + importance scoring (pure Python, zero deps).

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_memory.py -v
```

## LLM Providers

| Provider | Flag | Notes |
|----------|------|-------|
| llama.cpp | `--provider llamacpp` | Default, local GGUF files |
| Ollama | `--provider ollama` | Requires Ollama running |
| OpenRouter | `--provider openrouter` | Cloud API |
| OpenAI | `--provider openai` | Cloud API |
| vLLM | `--provider vllm` | Self-hosted |
| LM Studio | `--provider lmstudio` | Desktop app |

## License

MIT