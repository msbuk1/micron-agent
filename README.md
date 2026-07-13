# micron — Lightweight AI Agent

A minimal, file-based AI agent with **Obsidian-style memory**, **Markdown skills**, **knowledge vault**, and **tool calling** — designed to run on 1B-12B models via llama.cpp, LM Studio, or cloud APIs.

## Features

- 📁 **File-based memory** — JSONL storage, TF-IDF search, human-editable
- 📚 **Markdown skills** — Drop `.md` files in `context/skills/` with YAML frontmatter
- 🔌 **Python plugins** — Drop `.py` files in `context/plugins/` with `@tool` decorator
- 📖 **Knowledge vault** — Store reference docs in `context/knowledge/`, auto-injected by query relevance
- 🎭 **Composable personas** — Stack `.md` files in `context/persona/` for layered personality
- 🛠️ **17 tools + plugins** — web search, files, shell, math, Python eval, memory, knowledge
- 🔀 **Provider switching** — llamacpp, LM Studio, OpenRouter, OpenAI, Ollama, vLLM
- 💾 **Session persistence** — Auto-logs conversations to `context/sessions/`
- 🖥️ **Interactive CLI** — 15 slash commands, thinking indicator, history
- 🌐 **Web UI** — Dark-themed chat at `GET /` + file upload at `POST /upload`
- 🛡️ **Security** — Blocklists for dangerous commands (30+ patterns), directory traversal guards, resource limits
- ⚡ **Local-first** — Runs on Gemma4 12B, Qwen3.5, MiniCPM 1B, or any OpenAI-compatible API
- 🔒 **Human-in-the-loop** u2014 Write tools require explicit confirmation before execution

## Quick Start

```bash

# Resource limits for run_command (environment variables)
# MICRON_CMD_MAX_CPU: CPU time limit in seconds (default: 60)
# MICRON_CMD_MAX_MEMORY_MB: Memory limit in MB (default: 512)
# MICRON_CMD_MAX_PROCESSES: Max processes (default: 50)
# MICRON_CMD_MAX_FILES: Max open files (default: 100)
# 1. Clone and setup
git clone https://github.com/msbuk1/micron-agent.git && cd micron-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,server]"

# 2. Run CLI
python -m micron "What time is it?"

# 3. Interactive mode
python -m micron -i

# 4. Use LM Studio (or any OpenAI-compatible API)
python -m micron --provider lmstudio "Search for python tips"
```

## Configuration

Edit `micron.yaml` to configure providers:

```yaml
default_provider: lmstudio

providers:
  llamacpp:
    model: models/MiniCPM5-1B-Q8_0.gguf
  lmstudio:
    api_key: no_key
    base_url: http://localhost:1234/v1
    # model: gemma-4-12b-it-qat
  openrouter:
    api_key: <your-api-key>
    base_url: https://openrouter.ai/api/v1
    model: openrouter/auto
```

Override via CLI or env vars:
```bash
python -m micron --provider openrouter "query"
MICRON_PROVIDER=lmstudio python -m micron "query"
```

## CLI Usage

```bash
# Single query
python -m micron "What is 2+2?"

# Interactive mode
python -m micron -i

# List tools
python -m micron --list-tools

# Memory management
python -m micron --add-memory "User prefers dark mode"
python -m micron --search-memory "dark mode"
python -m micron --list-memories

# Server mode
python -m micron --server --port 8000
```

### Interactive Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/exit` | Exit interactive mode |
| `/clear` | Clear conversation history |
| `/mem` | List recent memories |
| `/tools` | Show available tools |
| `/model` | Show current model info |
| `/providers` | List configured providers |
| `/unload` | Unload model from RAM |
| `/reload` | Reload skills from disk |
| `/sessions` | List recent sessions |
| `/resume ID` | Resume a previous session |
| `/last` | Show last assistant response |

## Tools (14 + plugins)

| Tool | Description | Write? |
|------|-------------|--------|
| `web_search` | Search web (Firecrawl + DuckDuckGo fallback) | No |
| `fetch_url` | Fetch and extract URL content | No |
| `read_file` | Read file (supports line ranges) | No |
| `write_file` | Write/append file (security guardrails) | ✅ |
| `list_files` | List directory contents | No |
| `run_command` | Run shell command (30s timeout, blocklist) | ✅ |
| `calculate` | Evaluate math expression | No |
| `python_eval` | Execute Python code (sandboxed) | ✅ |
| `current_time` | Get current date/time | No |
| `save_memory` | Save fact to long-term memory | No |
| `search_knowledge` | Search knowledge documents | No |
| `write_knowledge` | Write document to knowledge vault | ✅ |
| `create_skill` | Create a new skill file | No |
| `search_skill_library` | Search skill files by keyword | No |
| `delete_file` | Delete a file (with confirmation) | ✅ |
| `edit_file` | Edit a file with syntax validation | ✅ |
| `list_skills` | List available skills | No |
| (plugins) | Custom tools via `@tool` decorator in `context/plugins/` | configurable |

## API Server

```bash
python -m micron --server

# Endpoints
GET  /                    # Web UI (dark-themed chat)
GET  /health              # Health check (includes rate_limiting_enabled, authentication_enabled)
GET  /tools               # List tools
POST /chat                # Chat (SSE stream or JSON) - supports rate limiting & authentication
POST /upload              # Upload file (saves to context/uploads/)
POST /memory              # Add memory
GET  /memory              # List memories
POST /memory/search       # Search memories
DELETE /memory/{id}       # Delete memory
POST /skills/reload       # Reload skills
```

```bash
# Example
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "stream": false}'
```

## Project Structure

```
```
micron/
├── context/
│   ├── skills/        # Tool definitions (Markdown + YAML)
│   ├── knowledge/     # Reference docs (auto-injected by query)
│   ├── memory/        # Long-term memory (memories.jsonl)
│   ├── sessions/      # Conversation logs (JSONL)
│   ├── persona/       # Personality layers
│   ├── plugins/       # Python plugin tools (@tool decorator)
│   └── uploads/       # Uploaded files (via web UI)
├── micron/
│   ├── __main__.py    # CLI + interactive mode
│   ├── agent.py       # Core agent loop
│   ├── llm.py         # LLM backends + OllamaToolAdapter
│   ├── memory.py      # JSONL + TF-IDF memory
│   ├── prompt.py      # Prompt builder (persona, memory, skills, knowledge)
│   ├── sessions.py    # Session persistence
│   ├── skills.py      # Skill loader + plugin integration
│   ├── server.py      # FastAPI + SSE server + web UI + file upload
│   ├── plugins/       # @tool decorator + discover_plugins()
│   └── tools/
│       ├── builtin.py # 14 built-in tools
│       └── registry.py
├── tests/
│   ├── test_memory.py
│   ├── test_skills.py
│   ├── test_registry.py
│   ├── test_agent.py  # Also tests OllamaToolAdapter + plugin discovery
│   └── test_server.py
├── micron.yaml        # Provider config
└── pyproject.toml
```

## Testing

```bash
python -m pytest tests/ -v        # 77 tests
```

## License

MIT
