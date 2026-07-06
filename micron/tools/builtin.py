"""Built-in tools for the agent."""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

# Working directory (reads from env var, resolved lazily)
_workdir_cache = None

def _get_workdir() -> Path:
    global _workdir_cache
    env_val = os.getenv("MICRON_WORKDIR", os.getcwd())
    new = Path(env_val).resolve()
    if _workdir_cache != new:
        _workdir_cache = new
    return _workdir_cache

def _resolve_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return _get_workdir() / path

# Firecrawl config (reads from env var set by CLI/server)
FIRECRAWL_URL = os.getenv("FIRECRAWL_URL", "http://localhost:3002")

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
        return [{"error": str(e)}]


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
        except:
            return {"url": url, "error": str(e), "content": ""}

def _fetch_url_basic(url: str, max_chars: int = 8000) -> dict:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        text = r.read().decode("utf-8", errors="replace")
        return {"url": url, "content": text[:max_chars]}

def read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
    """Read and return the text content of a file from the working directory.
    Optionally read specific line range (1-indexed). Use start_line/end_line for large files."""
    try:
        workdir = _get_workdir()
        target_path = (workdir / path).resolve()

        if not str(target_path).startswith(str(workdir.resolve())):
            return "Error: Security violation. Access denied."

        if not target_path.exists():
            return f"Error: File '{path}' does not exist."

        with open(target_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        total = len(lines)

        if start_line or end_line:
            start = max(0, (start_line or 1) - 1)
            end = end_line if end_line else total
            selected = lines[start:end]
            header = f"--- {path} (lines {start+1}-{min(end, total)} of {total}) ---\n"
            return header + "".join(selected)

        # Auto-truncate large files
        if total > 500:
            head = lines[:250]
            tail = lines[-50:]
            header = f"--- {path} ({total} lines, showing first 250 + last 50) ---\n"
            return header + "".join(head) + f"\n... ({total - 300} lines omitted) ...\n" + "".join(tail)

        return "".join(lines)
    except Exception as e:
        return f"Error reading file: {e}"

def write_file(path: str, content: str, mode: str = "w") -> str:
    """Write or append content to a text file."""
    try:
        workdir = _get_workdir()
        target_path = (workdir / path).resolve()

        if not str(target_path).startswith(str(workdir.resolve())):
            return "Error: Security violation. Access denied."

        target_path.parent.mkdir(parents=True, exist_ok=True)

        with open(target_path, mode, encoding="utf-8") as f:
            f.write(content)

        return f"Success: Wrote {len(content)} characters to {path}"
    except Exception as e:
        return f"Error writing file: {e}"

def list_files(path: str = ".") -> str:
    """List files and directories in the specified path."""
    try:
        workdir = _get_workdir()
        target_path = (workdir / path).resolve()

        if not str(target_path).startswith(str(workdir.resolve())):
            return "Error: Security violation. Access denied."

        if not target_path.exists():
            return f"Error: Path '{path}' does not exist."

        items = sorted(os.listdir(target_path))
        return "\n".join(items) if items else "Directory is empty."
    except Exception as e:
        return f"Error listing directory: {e}"

def run_command(cmd: str, cwd: str = ".", timeout: int = 30) -> str:
    """Run a shell command and return its output."""
    # Block dangerous commands
    blocked = ["rm -rf", "mkfs", "dd if=", ":(){ :|:& };:", "chmod -R 777", "> /dev/sd"]
    cmd_lower = cmd.lower().strip()
    for pattern in blocked:
        if pattern in cmd_lower:
            return f"Error: Command blocked for safety: '{pattern}' is not allowed."

    try:
        workdir = _resolve_path(cwd)

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=workdir,
        )

        output = result.stdout
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"

        return output.strip() if output.strip() else "Command executed successfully with no output returned."
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds."
    except Exception as e:
        return f"Error executing command: {e}"

def calculate(expression: str) -> dict:
    """Evaluate a math expression."""
    try:
        result = eval(expression, {"__builtins__": {}}, {"abs": abs, "round": round, "int": int, "float": float, "min": min, "max": max, "sum": sum, "pow": pow, "sqrt": __import__("math").sqrt, "pi": __import__("math").pi})
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"error": str(e)}

def python_eval(code: str) -> str:
    """Execute Python code and return the result."""
    # Block dangerous operations
    blocked = ["import os", "import subprocess", "import shutil", "__import__", "open(", "exec(", "eval("]
    code_lower = code.lower().strip()
    for pattern in blocked:
        if pattern in code_lower:
            return f"Error: Code blocked for safety: '{pattern}' is not allowed."

    if len(code) > 5000:
        return "Error: Code too long (max 5000 characters)."

    namespace = {"json": json, "datetime": datetime, "Path": Path}
    import io
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        try:
            result = eval(code, namespace, namespace)
            output = sys.stdout.getvalue()
            sys.stdout = old_stdout
            return output if output.strip() else repr(result)
        except SyntaxError:
            exec(code, namespace, namespace)
            output = sys.stdout.getvalue()
            sys.stdout = old_stdout
            return output if output.strip() else "Code executed successfully."
    except Exception as e:
        sys.stdout = old_stdout
        return f"Error executing code: {e}"

def current_time(timezone: str = "UTC") -> dict:
    """Get current date/time."""
    now = datetime.utcnow() if timezone == "UTC" else datetime.now()
    return {"iso": now.isoformat(), "date": now.date().isoformat(), "time": now.strftime("%H:%M:%S"), "timezone": timezone}

def save_memory(text: str, tags: list[str] = None, importance: int = 3) -> dict:
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

    return {"id": entry["id"], "saved": True, "text": text, "tags": entry["tags"]}


def search_memory(query: str = "", text: str = "", k: int = 5, tags: str = "") -> dict:
    """Search memories by keyword."""
    from micron.memory import Memory
    actual_query = text or query
    if not actual_query:
        return {"count": 0, "results": [], "error": "No query provided"}
    context_dir = os.getenv("MICRON_CONTEXT_DIR", str(Path(os.getenv("MICRON_WORKDIR", os.getcwd())) / "context"))
    memory_dir = Path(context_dir) / "memory"
    memory = Memory(memory_dir)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = memory.search(actual_query, k=k, tags=tag_list)
    return {
        "count": len(results),
        "results": [{"id": r.id, "text": r.text, "tags": r.tags, "importance": r.importance, "timestamp": r.timestamp} for r in results],
    }


def write_knowledge(title: str, content: str, tags: str = "") -> dict:
    """Save a knowledge document (markdown) to the knowledge folder."""
    import re
    context_dir = os.getenv("MICRON_CONTEXT_DIR", str(Path(os.getenv("MICRON_WORKDIR", os.getcwd())) / "context"))
    knowledge_dir = Path(context_dir) / "knowledge"
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
    return {"path": str(path), "slug": slug, "size": len(content), "saved": True}


# Tool registry for easy importing
TOOLS = {
    "web_search": web_search, "fetch_url": fetch_url, "read_file": read_file,
    "write_file": write_file, "list_files": list_files, "run_command": run_command,
    "calculate": calculate, "python_eval": python_eval, "current_time": current_time,
    "save_memory": save_memory, "search_memory": search_memory,
    "write_knowledge": write_knowledge,
}
