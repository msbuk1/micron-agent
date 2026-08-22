"""Built-in tools for the agent."""
import json
import os
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from micron.tools.decorator import tool

# Try to import resource module for Unix systems
try:
    import resource
    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False

# Working directory (reads from env var, resolved lazily)
_workdir_cache = None
_workdir_env_cache = None

def _get_workdir() -> Path:
    global _workdir_cache, _workdir_env_cache
    env_val = os.getenv("MICRON_WORKDIR")
    if not env_val:
        # Fall back to Config-resolved workdir (reads micron.yaml) rather
        # than os.getcwd(), so tools work without a Config having been
        # constructed elsewhere in the process.
        from micron.config import Config
        env_val = Config().get("workdir") or os.getcwd()
    # Invalidate cache if env var changes
    if _workdir_env_cache != env_val:
        _workdir_cache = None
        _workdir_env_cache = env_val
    new = Path(env_val).resolve()
    if _workdir_cache != new:
        _workdir_cache = new
    return _workdir_cache

def _resolve_path(path: str, *, must_exist: bool = False) -> Path | str:
    """Resolve a path relative to the working directory.

    Prevents path traversal — the resolved path must remain inside workdir.
    """
    workdir = _get_workdir().resolve()
    try:
        target = (workdir / path).resolve()
    except Exception as e:
        return f"Error resolving path: {e}"
    # Prevent path traversal — target must be inside workdir
    workdir_str = str(workdir)
    target_str = str(target)
    if target_str != workdir_str and not target_str.startswith(workdir_str + os.sep):
        return f"Error: Path '{path}' escapes the working directory."
    if must_exist and not target.exists():
        return f"Error: Path '{path}' does not exist."
    return target

# Timestamp format for trash file naming
TIMESTAMP_FMT = "%Y%m%d_%H%M%S"


def _get_trash_dir() -> Path:
    """Get (and create) the .trash directory under the working directory."""
    # Delegates to WorkspaceFS for locality, but keeps the same observable contract
    # for tests that import _get_trash_dir directly.
    from micron.workspace import WorkspaceFS

    ws = _ws() if "_ws" in globals() else WorkspaceFS(root=_get_workdir())
    d = ws.root / ".trash"
    d.mkdir(exist_ok=True)
    return d


# ── WorkspaceFS singleton — adapters delegate here ─────────────────────
_workspace_singleton = None
_workspace_env_snapshot = None


def _ws():
    """Return singleton WorkspaceFS bound to current MICRON_WORKDIR."""
    global _workspace_singleton, _workspace_env_snapshot
    # Use _get_workdir() as source of truth (handles env + Config fallback + cache)
    wd = _get_workdir()
    snap = str(wd)
    if _workspace_singleton is None or _workspace_env_snapshot != snap:
        from micron.workspace import WorkspaceFS

        _workspace_singleton = WorkspaceFS(root=wd)
        _workspace_env_snapshot = snap
    return _workspace_singleton


# Firecrawl config (reads from env var set by CLI/server)
FIRECRAWL_URL = os.getenv("FIRECRAWL_URL", "http://localhost:3002")

def _verify_write(path: Path, check_fn, description: str = "expected content") -> str | None:
    """Re-read a file after writing and verify a postcondition holds.

    Returns None on success, or an error message string on failure.
    """
    try:
        actual = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"could not re-read {path.name} for verification: {e}"
    if not check_fn(actual):
        snippet = actual[:150].replace("\n", "\\n")
        return f"post-write verification failed ({description}). File now starts with: {snippet}..."
    return None


def _set_command_resource_limits(decision=None):
    """Set resource limits for command execution.

    *decision* may be a :class:`~micron.tools.command_policy.Limit` instance
    whose non-``None`` fields override the env-var defaults.

    Called via ``preexec_fn`` — runs in the child after fork, before exec.
    Sets both soft and hard limits since this is a fresh process that will
    be replaced by exec() immediately after.
    """
    from micron.tools.command_policy import Limit

    if not _HAS_RESOURCE:
        return

    limit: Limit | None = decision if isinstance(decision, Limit) else None

    def _val(override, env_key, default):
        if override is not None:
            return override
        return int(os.getenv(env_key, default))

    try:
        if hasattr(resource, 'RLIMIT_CPU'):
            v = _val(limit.cpu if limit else None, "MICRON_CMD_MAX_CPU", "60")
            resource.setrlimit(resource.RLIMIT_CPU, (v, v))
    except (ValueError, OSError):
        pass

    try:
        if hasattr(resource, 'RLIMIT_AS'):
            mb = _val(limit.memory if limit else None, "MICRON_CMD_MAX_MEMORY_MB", "512")
            b = mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
    except (ValueError, OSError):
        pass

    try:
        if hasattr(resource, 'RLIMIT_NPROC'):
            v = _val(limit.procs if limit else None, "MICRON_CMD_MAX_PROCESSES", "50")
            resource.setrlimit(resource.RLIMIT_NPROC, (v, v))
    except (ValueError, OSError):
        pass

    try:
        if hasattr(resource, 'RLIMIT_NOFILE'):
            v = _val(limit.files if limit else None, "MICRON_CMD_MAX_FILES", "100")
            resource.setrlimit(resource.RLIMIT_NOFILE, (v, v))
    except (ValueError, OSError):
        pass


@tool(
    name="web_search",
    description="Search the web for current information, documentation, or news",
    query="Search query - use keywords, not a question. "
          "Good: 'python pandas drop duplicates keep last'. "
          "Bad: 'how do i drop duplicate rows in pandas but keep the final one please'",
    max_results="Number of results to return (default 5)",
)
def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web using Firecrawl."""
    try:
        resp = requests.post(
            f"{FIRECRAWL_URL}/v1/search",
            json={"query": query, "limit": max_results},
            timeout=15,
        )
        data = resp.json()
        results = []
        for item in data.get("data", data):
            if isinstance(item, dict) and "url" in item:
                results.append({"url": item["url"], "title": item.get("title", ""), "description": item.get("description", "")})
        if results:
            return results

        # Fallback: try DuckDuckGo via requests if Firecrawl returns empty
        fallback = _duckduckgo_search(query, max_results)
        if fallback:
            return fallback
        return results
    except Exception as e:
        # Fallback on error too
        fallback = _duckduckgo_search(query, max_results)
        if fallback:
            return fallback
        # Sanitize for Rich markup (avoid [Errno] causing MarkupError)
        msg = str(e).replace("[", "(").replace("]", ")")
        return [{"error": msg}]


def _duckduckgo_search(query: str, max_results: int = 5) -> list[dict]:
    """Fallback search using DuckDuckGo (ddgs library)."""
    try:
        import ddgs
        results = []
        with ddgs.DDGS() as d:
            for r in d.text(query, max_results=max_results):
                results.append({
                    "url": r.get("href", ""),
                    "title": r.get("title", ""),
                    "description": r.get("body", ""),
                })
        return results
    except Exception:
        return []

@tool(
    name="fetch_url",
    description="Fetch and extract text content from a URL",
    url="URL to fetch",
    max_chars="Maximum characters to return",
)
def fetch_url(url: str, max_chars: int = 8000) -> dict:
    """Fetch a URL and return its content."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return {"url": url, "title": soup.title.string if soup.title else "", "content": text[:max_chars]}
    except Exception as e:
        try:
            return _fetch_url_basic(url, max_chars)
        except Exception:
            return {"url": url, "error": str(e), "content": ""}

def _fetch_url_basic(url: str, max_chars: int = 8000) -> dict:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        text = r.read().decode("utf-8", errors="replace")
        return {"url": url, "content": text[:max_chars]}

@tool(
    name="read_file",
    description="Read the contents of a file from the working directory",
    path="Path to the file (relative to working directory)",
    start_line="Starting line number (1-indexed). Use for large files to read specific sections.",
    end_line="Ending line number (1-indexed, inclusive). Use with start_line for a range.",
)
def read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
    """Read and return the text content of a file from the working directory.
    Optionally read specific line range (1-indexed).
    Supports PDF extraction via pymupdf when available."""
    try:
        return _ws().read(path, start_line=start_line, end_line=end_line)
    except Exception as e:
        # Preserve legacy error string shapes for callers/tests that match "Error"
        msg = str(e)
        if "escapes" in msg.lower():
            return f"Error: Path '{path}' escapes the working directory."
        if "does not exist" in msg.lower() or isinstance(e, FileNotFoundError):
            return f"Error: Path '{path}' does not exist."
        if "pymupdf" in msg.lower():
            return f"Error: PDF extraction requires pymupdf. Install with: pip install pymupdf"
        if msg.startswith("Error"):
            return msg
        return f"Error reading file: {msg}"

@tool(
    name="write_file",
    description="Write or append content to a text file",
    write=True,
    path="Path to the file (relative to working directory)",
    content="Content to write",
    mode="Write mode: 'w' to overwrite, 'a' to append (default 'w')",
)
def write_file(path: str, content: str, mode: str = "w") -> str:
    """Write or append content to a text file."""
    if len(content) > 1_048_576:  # 1MB limit
        return f"Error: Content too large ({len(content)} chars, max 1048576)."
    try:
        _ws().write(path, content, mode=mode, verify=True)
        return f"Success: Wrote {len(content)} characters to {path}"
    except Exception as e:
        msg = str(e)
        if "escapes" in msg.lower():
            return f"Error: Path '{path}' escapes the working directory."
        if msg.startswith("Error"):
            return msg
        return f"Error writing file: {msg}"


@tool(
    name="paste_file",
    description="Save content to a file in context/uploads/. Auto-generates filename if not provided.",
    write=True,
    content="The content to save",
    filename="Custom filename. Auto-generates paste_<timestamp>.txt if omitted.",
)
def paste_file(content: str, filename: str = None) -> str:
    """Save content to a file in context/uploads/.

    Args:
        content: The content to save
        filename: Custom filename. Auto-generates paste_<timestamp>.txt if omitted.

    Returns:
        Success message with the filename
    """
    from micron.tools.error_handling import handle_error, success

    try:
        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"paste_{ts}.txt"

        ws = _ws()
        ws.write(f"context/uploads/{filename}", content, verify=True)
        return success(f"Pasted {len(content)} chars to {filename}")
    except Exception as e:
        return handle_error(
            "paste_file",
            e,
            "while saving pasted content"
        )


@tool(
    name="patch_file",
    description="Apply multiple find-and-replace patches to a file sequentially.",
    write=True,
    path="Path to the file (relative to workdir)",
    patches="List of dicts with 'old' (text to find) and 'new' (replacement)",
)
def patch_file(path: str, patches: list[dict]) -> str:
    """Apply multiple patches to a file.
    
    Each patch is a dict with 'old' and 'new' keys (like sed/find-replace).
    
    Args:
        path: Path to the file (relative to workdir)
        patches: List of dicts with 'old' (text to find) and 'new' (replacement)
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success

    try:
        ws = _ws()
        applied = ws.patch(path, patches)
        return success(f"Patched {path}: {applied}/{len(patches)} patches applied")
    except Exception as e:
        msg = str(e)
        if "No patches" in msg or "none of the" in msg.lower():
            return handle_error(
                "patch_file",
                Exception("No patches applied"),
                "none of the 'old' texts were found in the file"
            )
        if "escapes" in msg.lower():
            return f"Error: Path '{path}' escapes the working directory."
        return handle_error(
            "patch_file",
            e,
            f"while patching {path}"
        )


@tool(
    name="list_files",
    description="List all files and directories in a specified path",
    path='Directory path to list (relative to working directory, default ".")',
)
def list_files(path: str = ".") -> str:
    """List files and directories in the specified path."""
    try:
        entries = _ws().list(path)
        if not entries:
            return "Directory is empty."
        return "\n".join(e.name for e in entries)
    except Exception as e:
        msg = str(e)
        if "escapes" in msg.lower():
            return f"Error: Path '{path}' escapes the working directory."
        if "does not exist" in msg.lower():
            return f"Error: Path '{path}' does not exist."
        if msg.startswith("Error"):
            return msg
        return f"Error listing directory: {msg}"


@tool(
    name="tree",
    description="Display directory structure as a tree with depth and extension filtering.",
    path="Path to display (relative to workdir)",
    max_depth="Maximum depth to display (default 3)",
    show_files="Show files (default True)",
    ext="Only show files with this extension (e.g. 'py' for .py files)",
)
def tree(path: str = ".", max_depth: int = 3, show_files: bool = True, ext: str = None) -> str:
    """Display directory structure as a tree.
    
    Args:
        path: Path to display (relative to workdir)
        max_depth: Maximum depth to display (default 3)
        show_files: Show files (default True)
        ext: Only show files with this extension (e.g. 'py' for .py files)
        
    Returns:
        Tree representation of directory
    """
    try:
        return _ws().tree(path, max_depth=max_depth, show_files=show_files, ext=ext)
    except Exception as e:
        msg = str(e)
        if "escapes" in msg.lower():
            return f"Error: Path '{path}' escapes the working directory."
        if "does not exist" in msg.lower():
            return f"Error: Path '{path}' does not exist."
        if msg.startswith("Error"):
            return msg
        return f"Error: {msg}"


@tool(
    name="run_command",
    description="Run a shell command in the working directory (30s timeout, blocklist enforced)",
    write=True,
    cmd="Shell command to execute",
    cwd="Working directory (relative to workdir)",
    timeout="Maximum execution time in seconds (default 30)",
)
def run_command(cmd: str, cwd: str = ".", timeout: int = 30) -> str:
    """Run a shell command and return its output."""
    import shlex
    from micron.tools.error_handling import handle_error, success
    from micron.tools.command_policy import CommandPolicy, Deny, Limit

    # Length guard
    if len(cmd) > 500:
        return handle_error("run_command", Exception("Command too long"), "command exceeds 500 character limit")

    # Parse
    try:
        args = shlex.split(cmd)
    except ValueError as e:
        return handle_error("run_command", Exception(f"Invalid command syntax: {e}"), "could not parse command")

    # Evaluate policy
    decision = CommandPolicy().evaluate(args)
    if isinstance(decision, Deny):
        return handle_error("run_command", Exception(decision.reason), decision.reason)

    # Resource limits are applied to the child only via preexec_fn, which
    # runs after fork() in the child before exec(). resource.setrlimit is
    # async-signal-safe (a direct syscall, no Python locks), so this is
    # thread-safe even though the TUI runs the agent in a worker thread.
    # Setting limits on the parent instead would constrain the parent's
    # own fds/sockets (Textual + LLM) and hang the UI.

    # Resolve cwd and run
    try:
        workdir = _resolve_path(cwd)
        if isinstance(workdir, str):
            return workdir

        result = subprocess.run(
            args, shell=False, capture_output=True, text=True,
            timeout=timeout, cwd=workdir,
            preexec_fn=lambda: _set_command_resource_limits(decision),
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"
        return output.strip() if output.strip() else success("Command executed successfully")
    except subprocess.TimeoutExpired as e:
        return handle_error("run_command", e, f"command timed out after {timeout} seconds")
    except FileNotFoundError as e:
        return handle_error("run_command", e, f"command not found: {args[0]}")
    except Exception as e:
        return handle_error("run_command", e, "while executing command")

@tool(
    name="calculate",
    description="Safely evaluate a mathematical expression",
    expression='Mathematical expression (e.g., "2 + 2", "sqrt(16) * 3")',
)
def calculate(expression: str) -> str:
    """Evaluate a math expression safely using asteval."""
    try:
        import asteval
        import math
        aeval = asteval.Interpreter(
            usersyms={
                "abs": abs, "round": round, "int": int, "float": float,
                "min": min, "max": max, "sum": sum, "pow": pow,
                "sqrt": math.sqrt, "pi": math.pi, "e": math.e,
                "sin": math.sin, "cos": math.cos, "tan": math.tan,
                "log": math.log, "log10": math.log10, "ceil": math.ceil,
                "floor": math.floor, "factorial": math.factorial,
            },
        )
        result = aeval.eval(expression)
        if result is None and aeval.error:
            return f"Error: {aeval.error[0].get_error()}"
        return str(result) if result is not None else "Error: no result"
    except ImportError:
        return "Error: calculate requires the 'asteval' package. Install with: pip install asteval"
    except Exception as e:
        return f"Error: {e}"

@tool(
    name="python_eval",
    description="Execute a restricted subset of Python code (sandboxed: no imports, no filesystem access) and return the result.",
    write=True,
    code="Python code to execute (pure expressions and print statements only, max 5000 chars)",
)
def python_eval(code: str) -> str:
    """Execute a restricted subset of Python code and return the result.

    The sandbox allows only pure expressions and print statements.
    It cannot import new modules, access the filesystem, or run arbitrary code.
    """
    try:
        import asteval
    except ImportError:
        return "Error: python_eval requires the 'asteval' package. Install with: pip install asteval"

    if len(code) > 5000:
        return "Error: Code too long (max 5000 characters)."

    # Create a sandboxed interpreter with safe builtins
    aeval = asteval.Interpreter(
        usersyms={"json": json, "datetime": datetime},
        no_print=False,
        raise_errors=True,
    )

    try:
        result = aeval.eval(code)
        if result is None and aeval.error:
            return f"Error: {aeval.error[0].get_error()}"
        return str(result) if result is not None else "Code executed successfully."
    except Exception as e:
        return f"Error executing code: {e}"

@tool(
    name="current_time",
    description="Get current date and time",
    timezone="Timezone (UTC or local)",
)
def current_time(timezone: str = "UTC") -> str:
    """Get current date/time."""
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc) if timezone == "UTC" else datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S") + f" ({timezone})"

@tool(
    name="save_memory",
    description="Save something to long-term memory for future reference",
    text="What to remember",
    tags="Tags for categorization",
    importance="Importance level (1-5, 5=highest)",
)
def save_memory(text: str, tags: list[str] = None, importance: int = 3) -> str:
    """Save something to long-term memory."""
    import uuid
    context_dir = os.getenv("MICRON_CONTEXT_DIR", str(Path(os.getenv("MICRON_WORKDIR", os.getcwd())) / "context"))
    memory_dir = Path(context_dir) / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    memory_file = memory_dir / "memories.jsonl"

    if isinstance(tags, str):
        tags = [t.strip().strip("'\"") for t in tags.strip("[]").split(",") if t.strip()]

    try:
        importance = int(importance)
    except (ValueError, TypeError):
        importance = 3

    entry = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": datetime.now().isoformat(),
        "text": text,
        "tags": tags or [],
        "importance": max(1, min(5, importance)),
        "metadata": {},
    }

    with open(memory_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return f"Saved: {text}"


@tool(
    name="search_memory",
    description="Search long-term memories by keyword. Returns ranked memories by relevance.",
    query="Search query for memories",
    k="Number of results to return (default 5)",
)
def search_memory_tool(query: str = "", k: int = 5) -> str:
    """Search long-term memories."""
    from micron.memory import Memory

    if not query.strip():
        return "(no search query)"
    context_dir = os.getenv("MICRON_CONTEXT_DIR", str(Path(os.getenv("MICRON_WORKDIR", os.getcwd())) / "context"))
    mem = Memory(Path(context_dir) / "memory")
    results = mem.search(query, k=k)
    if not results:
        return "(no relevant memories)"
    lines = []
    for r in results:
        tags = " ".join(f"#{t}" for t in r.tags) if r.tags else ""
        lines.append(f"[{r.id}] {r.text} {tags} (importance {r.importance})")
    return "\n".join(lines)


@tool(
    name="search_knowledge",
    description="Search knowledge documents and long-term memories by keyword. Returns ranked results by relevance.",
    query="The search query to find in knowledge documents",
    k="Number of results to return (default 5)",
)
def search_knowledge(query: str = "", k: int = 5) -> str:
    """Search knowledge documents using TF-IDF scoring. Returns ranked markdown snippets."""
    import os
    from pathlib import Path

    from micron.knowledge import KnowledgeIndex

    # Preserve sentinel order: dir missing -> no docs -> no search query (matches old)
    workdir = Path(os.getenv("MICRON_WORKDIR", os.getcwd()))
    knowledge_dir = workdir / "context" / "knowledge"
    ctx_env = os.getenv("MICRON_CONTEXT_DIR")
    if ctx_env:
        alt = Path(ctx_env) / "knowledge"
        if alt.exists():
            knowledge_dir = alt
        # Also check alt for existence when workdir missing
        if not knowledge_dir.exists() and alt.exists():
            knowledge_dir = alt
    if not knowledge_dir.exists():
        return "(knowledge directory not found)"
    ki_probe = KnowledgeIndex(knowledge_dir)
    if ki_probe.size == 0:
        return "(no knowledge documents)"
    if not query.strip():
        return "(no search query)"
    # Non-empty query: delegate to KnowledgeIndex (reuse probe)
    hits = ki_probe.search(query, k=k)
    if not hits:
        return "(no relevant knowledge)"
    out = []
    for h in hits:
        out.append(f"[{h.slug}] (score: {h.score:.2f}) {h.snippet}...")
    return "\n".join(out)

@tool(
    name="write_knowledge",
    description="Save a markdown document to the knowledge folder (context/knowledge/).",
    write=True,
    title="Document title (used to generate the filename)",
    content="Markdown content of the knowledge document",
    tags="Optional comma-separated tags for organization",
)
def write_knowledge(title: str, content: str, tags: str = "") -> str:
    """Save a knowledge document (markdown) to the knowledge folder."""
    workdir = Path(os.getenv("MICRON_WORKDIR", os.getcwd()))
    knowledge_dir = workdir / "context" / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", title.lower().replace(" ", "_"))[:50]
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        slug = "doc"
    path = knowledge_dir / f"{slug}.md"

    if not content.startswith("# "):
        content = f"# {title}\n\n{content}"

    tag_line = ""
    if tags:
        tags_list = [t.strip() for t in tags.split(",") if t.strip()]
        tag_line = f"\n\nTags: {', '.join(tags_list)}"
    content += tag_line

    path.write_text(content)

    verify_err = _verify_write(
        path,
        lambda actual: actual == content,
        "knowledge content matches",
    )
    if verify_err:
        return f"Error: {verify_err}"

    return f"Saved: {path}"


@tool(
    name="create_skill",
    description="Create a new skill file in context/skills/. The skill is loaded after /reload.",
    write=True,
    param_descs={
        "name": "Skill name (lowercase, no spaces)",
        "description": "Description of what the skill does",
        "parameters": "JSON schema string for the tool parameters (optional)",
        "module": "Python module path for the tool function (optional)",
        "write": "Whether the skill is a write tool (optional)",
    },
)
def create_skill(name: str, description: str, parameters: str = "", module: str = "", write: bool = False) -> str:
    """Create a new skill file in context/skills/. The skill is loaded after /reload."""
    workdir = _get_workdir()
    skills_dir = workdir / "context" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^a-z0-9_-]", "_", name.lower().replace(" ", "_"))[:50]
    if not slug:
        return "Error: Invalid skill name."

    # Read-only core protection
    if slug in CORE_SKILLS:
        return f"Error: '{slug}' is a core skill and cannot be overwritten."

    path = skills_dir / f"{slug}.md"
    if path.exists():
        return f"Error: Skill '{slug}' already exists. Use write_file to modify it."

    # Linter guardrail: validate YAML before saving
    if parameters:
        try:
            import yaml
            test_yaml = f"parameters:\n{parameters}"
            parsed = yaml.safe_load(test_yaml)
            if not isinstance(parsed.get("parameters"), dict):
                return "Error: parameters must be a valid YAML mapping."
        except Exception as e:
            return f"Error: Invalid YAML in parameters: {e}"

    lines = ["---"]
    lines.append(f"name: {slug}")
    lines.append(f"description: {description}")
    lines.append(f"write: {'true' if write else 'false'}")
    if module:
        lines.append(f"module: {module}")
    if parameters:
        lines.append("parameters:")
        lines.append(parameters)
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")
    lines.append(f"{description}")
    lines.append("")
    if module:
        lines.append(f"Implementation: `{module}.{slug}`")
    else:
        lines.append("This is a prompt-based skill. Add instructions below.")
    lines.append("")
    lines.append("## Instructions")
    lines.append("")
    lines.append("Add your skill instructions here.")
    lines.append("")

    written = "\n".join(lines)
    path.write_text(written)

    verify_err = _verify_write(
        path,
        lambda actual: actual == written,
        "skill content matches",
    )
    if verify_err:
        return f"Error: {verify_err}"

    return f"Created skill: {path.relative_to(workdir)}\nRun /reload to activate it."


# Core skills that cannot be overwritten
CORE_SKILLS = {"web_search", "fetch_url", "read_file", "write_file", "list_files",
               "run_command", "calculate", "python_eval", "current_time",
               "save_memory", "search_knowledge", "write_knowledge",
               "create_skill", "search_skill_library"}


@tool(
    name="list_skills",
    description="List all available skills with descriptions.",
    query="Optional filter keyword to match against skill names/descriptions",
)
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
            name = ""
            description = ""
            is_write = False
            
            # Parse frontmatter
            in_frontmatter = False
            for line in content.split("\n"):
                if line.strip() == "---":
                    in_frontmatter = not in_frontmatter
                    continue
                if in_frontmatter:
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip()
                    elif line.startswith("description:"):
                        description = line.split(":", 1)[1].strip()
                    elif line.startswith("write:"):
                        is_write = line.split(":", 1)[1].strip().lower() == "true"
            
            if not name:
                name = f.stem
            
            skills.append({
                "name": name,
                "file": f.name,
                "description": description,
                "write": is_write
            })
        except Exception as e:
            continue

    if not skills:
        return "No skills found in context/skills/"

    # Filter by query if provided
    if query:
        query_lower = query.lower()
        skills = [s for s in skills if query_lower in s["name"].lower() or query_lower in s["description"].lower()]

    # Format output
    lines = []
    for skill in skills:
        write_marker = " ✏️" if skill["write"] else ""
        lines.append(f"{skill['name']}{write_marker}: {skill['description']}")
    
    return "\n".join(lines)


@tool(
    name="delete_file",
    description="Delete a file from the working directory (moves to .trash/ for recovery)",
    write=True,
    path="Path to the file to delete (relative to workdir)",
)
def delete_file(path: str) -> str:
    """Delete a file from the working directory (moves to .trash/ for recovery).
    
    Args:
        path: Path to the file to delete (relative to workdir)
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success

    try:
        entry = _ws().delete(path)
        return success(f"Deleted {entry.original} (recoverable via /restore)")
    except Exception as e:
        msg = str(e)
        if "Cannot delete directory" in msg or "is a directory" in msg.lower():
            return handle_error(
                "delete_file",
                Exception(f"Cannot delete directory '{path}'"),
                "use run_command with rm -rf to delete directories"
            )
        if "escapes" in msg.lower():
            return f"Error: Path '{path}' escapes the working directory."
        if "does not exist" in msg.lower():
            return f"Error: Path '{path}' does not exist."
        return handle_error(
            "delete_file",
            e,
            f"while deleting {path}"
        )


@tool(
    name="restore_file",
    description="Restore a file from the .trash/ directory.",
    write=True,  # mutates filesystem (moves from trash back to workdir)
    filename="Name of the file in .trash/ (from the /trash listing)",
)
def restore_file(filename: str) -> str:
    """Restore a file from .trash/ directory.
    
    Args:
        filename: Name of the file in .trash/ (from /trash listing)
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success

    try:
        restored = _ws().restore(filename)
        return success(f"Restored to {restored.name}")
    except Exception as e:
        msg = str(e)
        if "not found in trash" in msg.lower() or "no trash directory" in msg.lower():
            return handle_error(
                "restore_file",
                Exception(f"File '{filename}' not found in trash"),
                "use /trash to see available files"
            )
        if "multiple files match" in msg.lower():
            return handle_error(
                "restore_file",
                Exception(f"Multiple files match '{filename}'"),
                msg
            )
        return handle_error(
            "restore_file",
            e,
            f"while restoring {filename}"
        )


@tool(
    name="list_trash",
    description="List files in the .trash/ directory (recoverable deleted files).",
)
def list_trash() -> str:
    """List files in .trash/ directory.
    
    Returns:
        List of trashed files with timestamps, or empty message
    """
    from micron.tools.error_handling import success
    from datetime import datetime

    ws = _ws()
    trash_dir = ws.root / ".trash"
    if not trash_dir.exists():
        return success("Trash is empty (no files deleted yet)")

    entries = ws.trash()
    if not entries:
        return success("Trash is empty")

    lines = ["🗑️ Trash:"]
    for e in entries:
        time_str = e.trashed_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"  {e.name}  ({e.original}, deleted {time_str})")
    return "\n".join(lines)


@tool(
    name="edit_file",
    description="Edit a file by replacing old_text with new_text. Creates a .bak backup for undo.",
    write=True,
    path="Path to the file (relative to workdir)",
    old_text="Text to replace",
    new_text="Replacement text",
)
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Edit a file by replacing old_text with new_text.
    
    Creates a .bak backup before editing for undo support.
    
    Args:
        path: Path to the file (relative to workdir)
        old_text: Text to replace
        new_text: Replacement text
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success

    try:
        ws = _ws()
        # Pre-check for missing text to keep legacy error shape ("Text not found")
        try:
            exists = ws.exists(path)
            if not exists:
                return f"Error: Path '{path}' does not exist."
            # Peek content for not-found case to preserve message
            current = ws.read(path)
            if old_text not in current:
                return handle_error(
                    "edit_file",
                    Exception(f"Text not found in {path}"),
                    "the specified text to replace was not found"
                )
        except Exception as pe:
            msg = str(pe)
            if "escapes" in msg.lower():
                return f"Error: Path '{path}' escapes the working directory."
            if "does not exist" in msg.lower():
                return f"Error: Path '{path}' does not exist."
        # Delegate — WorkspaceFS handles .bak, syntax validation, verification
        ws.edit(path, old_text, new_text)
        return success(f"Edited {path} (replaced {len(old_text)} chars with {len(new_text)} chars)")
    except Exception as e:
        msg = str(e)
        if "Syntax error" in msg:
            return handle_error("edit_file", e, msg)
        if "escapes" in msg.lower():
            return f"Error: Path '{path}' escapes the working directory."
        return handle_error(
            "edit_file",
            e,
            f"while editing {path}"
        )


@tool(
    name="undo_file",
    description="Restore a file from its .bak backup created by edit_file.",
    write=True,  # mutates filesystem (restores from backup)
    path="Path to the file to restore (relative to workdir)",
)
def undo_file(path: str) -> str:
    """Restore a file from its .bak backup.
    
    Args:
        path: Path to the file to restore (relative to workdir)
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success

    try:
        _ws().undo(path)
        return success(f"Restored {path} from backup")
    except Exception as e:
        msg = str(e)
        if "No backup" in msg or "not found" in msg.lower():
            return handle_error(
                "undo_file",
                Exception(f"No backup found for {path}"),
                "edit_file creates .bak backups automatically"
            )
        return handle_error(
            "undo_file",
            e,
            f"while restoring {path}"
        )


@tool(
    name="search_skill_library",
    description="Search existing skills by keyword. Use before creating a new skill to check if one already exists.",
    query="Keywords to search for in skill names and descriptions",
    text="Alias for query",
)
def search_skill_library(query: str = "", text: str = "") -> str:
    """Search skill files by keyword. Returns matching skills with descriptions."""
    actual_query = text or query
    if not actual_query:
        return "Error: No query provided."

    workdir = _get_workdir()
    skills_dir = workdir / "context" / "skills"
    if not skills_dir.exists():
        return "No skills found."

    query_lower = actual_query.lower()
    query_words = set(query_lower.split())
    results = []

    for f in sorted(skills_dir.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
            content_lower = content.lower()
            score = sum(1 for word in query_words if word in content_lower)
            if score == 0:
                continue

            # Extract frontmatter description
            desc = ""
            in_frontmatter = False
            for line in content.split("\n"):
                if line.strip() == "---":
                    in_frontmatter = not in_frontmatter
                    continue
                if in_frontmatter and line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
                    break

            results.append({"file": f.name, "score": score, "description": desc})
        except Exception:
            continue

    if not results:
        return f"No skills match '{actual_query}'."

    results.sort(key=lambda x: x["score"], reverse=True)
    lines = []
    for r in results[:10]:
        lines.append(f"  {r['file']}: {r['description']} (score: {r['score']})")
    return "\n".join(lines)


@tool(
    name="purge_trash",
    description="Empty the .trash/ directory permanently (files cannot be recovered).",
    write=True,
)
def purge_trash() -> str:
    """Permanently delete all files in .trash/."""
    from micron.tools.error_handling import success

    count = _ws().purge_trash()
    if count == 0:
        return success("Trash is already empty.")
    return success(f"Purged {count} file(s) from trash.")