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
    env_val = os.getenv("MICRON_WORKDIR", os.getcwd())
    # Invalidate cache if env var changes
    if _workdir_env_cache != env_val:
        _workdir_cache = None
        _workdir_env_cache = env_val
    new = Path(env_val).resolve()
    if _workdir_cache != new:
        _workdir_cache = new
    return _workdir_cache

def _resolve_path(path: str, *, must_exist: bool = False) -> Path | str:
    """Resolve a path relative to the working directory."""
    workdir = _get_workdir().resolve()
    try:
        target = (workdir / path).resolve()
    except Exception as e:
        return f"Error resolving path: {e}"
    if must_exist and not target.exists():
        return f"Error: Path '{path}' does not exist."
    return target

# Firecrawl config (reads from env var set by CLI/server)
FIRECRAWL_URL = os.getenv("FIRECRAWL_URL", "http://localhost:3002")

def _set_command_resource_limits():
    """Set resource limits for command execution."""
    if not _HAS_RESOURCE:
        return
    
    try:
        if hasattr(resource, 'RLIMIT_CPU'):
            max_cpu_time = int(os.getenv("MICRON_CMD_MAX_CPU", "60"))
            resource.setrlimit(resource.RLIMIT_CPU, (max_cpu_time, max_cpu_time))
    except (ValueError, OSError):
        pass
    
    try:
        if hasattr(resource, 'RLIMIT_AS'):
            max_memory_mb = int(os.getenv("MICRON_CMD_MAX_MEMORY_MB", "512"))
            max_memory_bytes = max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (max_memory_bytes, max_memory_bytes))
    except (ValueError, OSError):
        pass
    
    try:
        if hasattr(resource, 'RLIMIT_NPROC'):
            max_processes = int(os.getenv("MICRON_CMD_MAX_PROCESSES", "50"))
            resource.setrlimit(resource.RLIMIT_NPROC, (max_processes, max_processes))
    except (ValueError, OSError):
        pass
    
    try:
        if hasattr(resource, 'RLIMIT_NOFILE'):
            max_files = int(os.getenv("MICRON_CMD_MAX_FILES", "100"))
            resource.setrlimit(resource.RLIMIT_NOFILE, (max_files, max_files))
    except (ValueError, OSError):
        pass


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
    Optionally read specific line range (1-indexed).
    Supports PDF extraction via pymupdf when available."""
    target_path = _resolve_path(path, must_exist=True)
    if isinstance(target_path, str):
        return target_path

    # PDF extraction
    if str(target_path).lower().endswith(".pdf"):
        try:
            import pymupdf
            doc = pymupdf.open(str(target_path))
            total_pages = len(doc)
            lines = []
            for i, page in enumerate(doc):
                lines.append(f"--- Page {i+1}/{total_pages} ---")
                lines.append(page.get_text())
                lines.append("")
            doc.close()
            text = "\n".join(lines)
            # Apply line range if specified
            if start_line or end_line:
                all_lines = text.splitlines(keepends=True)
                start = max(0, (start_line or 1) - 1)
                end = end_line if end_line else len(all_lines)
                return f"--- {path} (PDF, pages {start+1}-{min(end, len(all_lines))} of {len(all_lines)}) ---\n" + "".join(all_lines[start:end])
            # Auto-truncate large PDFs
            if len(lines) > 500:
                return f"--- {path} (PDF, {total_pages} pages, showing first 250 + last 50 lines) ---\n" + "\n".join(lines[:250]) + f"\n... ({len(lines) - 300} lines omitted) ...\n" + "\n".join(lines[-50:])
            return text
        except ImportError:
            return f"Error: PDF extraction requires pymupdf. Install with: pip install pymupdf"
        except Exception as e:
            return f"Error reading PDF: {e}"

    try:
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
    except UnicodeDecodeError:
        # Try binary file — read as bytes and return size info
        try:
            with open(target_path, "rb") as f:
                data = f.read()
            return f"--- {path} (binary file, {len(data)} bytes) ---\n[Binary content — cannot display as text]"
        except Exception as e2:
            return f"Error reading file: {e2}"
    except Exception as e:
        return f"Error reading file: {e}"

def write_file(path: str, content: str, mode: str = "w") -> str:
    """Write or append content to a text file."""
    target_path = _resolve_path(path)
    if isinstance(target_path, str):
        return target_path

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with open(target_path, mode, encoding="utf-8") as f:
            f.write(content)

        return f"Success: Wrote {len(content)} characters to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def paste_file(path: str, content: str, line: int = 0) -> str:
    """Paste content to a file at a specific line position.
    
    Args:
        path: Path to the file (relative to workdir)
        content: Text content to paste
        line: Line number to insert at (0 = append to end, 1 = first line)
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success
    
    target = _resolve_path(path, must_exist=False)
    if isinstance(target, str):
        return target
    
    try:
        # Create parent directories if needed
        target.parent.mkdir(parents=True, exist_ok=True)
        
        if line <= 0:
            # Append to end (default)
            with open(target, "a", encoding="utf-8") as f:
                f.write(content)
            return success(f"Pasted {len(content)} chars to {path} (appended)")
        
        # Insert at specific line
        if target.exists():
            lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            lines = []
        
        # Convert to 0-indexed
        idx = line - 1
        if idx < 0:
            idx = 0
        
        # Ensure content ends with newline
        if content and not content.endswith("\n"):
            content += "\n"
        
        # Insert at position
        lines.insert(idx, content)
        
        target.write_text("".join(lines), encoding="utf-8")
        return success(f"Pasted {len(content)} chars to {path} at line {line}")
    
    except Exception as e:
        return handle_error(
            "paste_file",
            e,
            f"while pasting to {path}"
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
    
    target = _resolve_path(path, must_exist=True)
    if isinstance(target, str):
        return target
    
    try:
        content = target.read_text(encoding="utf-8")
        original = content
        applied = 0
        
        for patch in patches:
            old_text = patch.get("old", "")
            new_text = patch.get("new", "")
            
            if not old_text:
                continue
            
            if old_text in content:
                content = content.replace(old_text, new_text, 1)
                applied += 1
        
        if applied == 0:
            return handle_error(
                "patch_file",
                Exception("No patches applied"),
                "none of the 'old' texts were found in the file"
            )
        
        target.write_text(content, encoding="utf-8")
        return success(f"Patched {path}: {applied}/{len(patches)} patches applied")
    
    except Exception as e:
        return handle_error(
            "patch_file",
            e,
            f"while patching {path}"
        )


def list_files(path: str = ".") -> str:
    """List files and directories in the specified path."""
    target_path = _resolve_path(path, must_exist=True)
    if isinstance(target_path, str):
        return target_path

    try:
        items = sorted(os.listdir(target_path))
        return "\n".join(items) if items else "Directory is empty."
    except Exception as e:
        return f"Error listing directory: {e}"


def tree(path: str = ".", max_depth: int = 3, show_files: bool = True) -> str:
    """Display directory structure as a tree.
    
    Args:
        path: Path to display (relative to workdir)
        max_depth: Maximum depth to display (default 3)
        show_files: Show files (default True)
        
    Returns:
        Tree representation of directory
    """
    from pathlib import Path
    
    target = _resolve_path(path, must_exist=True)
    if isinstance(target, str):
        return target
    
    def build_tree(dir_path: Path, prefix: str = "", depth: int = 0) -> list[str]:
        if depth >= max_depth:
            return []
        
        lines = []
        try:
            entries = sorted(dir_path.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            return [f"{prefix}[Permission Denied]"]
        
        # Filter entries
        if not show_files:
            entries = [e for e in entries if e.is_dir()]
        
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            
            if entry.is_dir():
                lines.append(f"{prefix}{connector}{entry.name}/")
                extension = "    " if is_last else "│   "
                lines.extend(build_tree(entry, prefix + extension, depth + 1))
            else:
                lines.append(f"{prefix}{connector}{entry.name}")
        
        return lines
    
    result = [target.name + "/"]
    result.extend(build_tree(target))
    return "\n".join(result)


def run_command(cmd: str, cwd: str = ".", timeout: int = 30) -> str:
    """Run a shell command and return its output.
    
    Args:
        cmd: Shell command to execute
        cwd: Working directory (relative to workdir)
        timeout: Maximum execution time in seconds
        
    Returns:
        Command output or error message
    """
    from micron.tools.error_handling import handle_error, success
    import re
    import shlex
    
    # Restrict mode. If MICRON_UNRESTRICTED=1, only block truly destructive patterns.
    unrestricted = os.getenv("MICRON_UNRESTRICTED", "").lower() in ("1", "true", "yes")

    # Additional safety checks
    _set_command_resource_limits()
    if len(cmd) > 500:
        return handle_error(
            "run_command",
            Exception("Command too long"),
            "command exceeds 500 character limit"
        )

    # Parse command into args (shell-safe)
    try:
        args = shlex.split(cmd)
    except ValueError as e:
        return handle_error(
            "run_command",
            Exception(f"Invalid command syntax: {e}"),
            "could not parse command"
        )
    
    if not args:
        return handle_error(
            "run_command",
            Exception("Empty command"),
            "no command provided"
        )
    
    # Check first argument (command name) against blocklist
    cmd_name = args[0].lower()
    
    # Blocked command names (always blocked)
    blocked_commands = {
        "rm", "mkfs", "dd", "sudo", "chown", "chmod",
        "chsh", "useradd", "userdel", "passwd",
        "wget", "curl", "apt-get", "yum", "pacman",
    }
    
    # Check if command is blocked
    if cmd_name in blocked_commands and not unrestricted:
        # Special case: allow safe rm usage (rm file.txt, not rm -rf)
        if cmd_name == "rm" and not any(a.startswith("-") and "r" in a for a in args[1:]):
            pass  # Allow safe rm
        else:
            return handle_error(
                "run_command",
                Exception(f"Command '{cmd_name}' is blocked"),
                f"blocked command for security reasons"
            )
    
    # Check for dangerous flags and patterns in ALL args (including command name)
    if not unrestricted:
        for i, arg in enumerate(args):
            arg_lower = arg.lower()
            
            # Block recursive delete flags
            if cmd_name == "rm" and arg_lower.startswith("-") and "r" in arg_lower:
                return handle_error(
                    "run_command",
                    Exception("Recursive delete is blocked"),
                    "rm -r/-rf is not allowed"
                )
            
            # Block pipe operator
            if arg == "|":
                return handle_error(
                    "run_command",
                    Exception("Pipe operator is blocked"),
                    "shell pipes are not allowed"
                )
            
            # Block shell execution via path (./ or ~/)
            if arg.startswith("./") or arg.startswith("~/"):
                return handle_error(
                    "run_command",
                    Exception("Executing scripts from path is blocked"),
                    "cannot execute ./script or ~/script"
                )
            
            # Block command substitution
            if arg.startswith("$(") or arg.startswith("`"):
                return handle_error(
                    "run_command",
                    Exception("Command substitution is blocked"),
                    "cannot use $(...) or backticks"
                )
            
            # Block redirection to block devices
            if arg.startswith("/dev/sd") or arg.startswith("/dev/nvme"):
                return handle_error(
                    "run_command",
                    Exception("Redirect to block device is blocked"),
                    "cannot write to block devices"
                )
            
            # Block shell names as arguments (bash, sh, zsh)
            if arg_lower in ("bash", "sh", "zsh"):
                return handle_error(
                    "run_command",
                    Exception("Shell execution is blocked"),
                    "cannot execute bash/sh/zsh"
                )
    
    try:
        workdir = _resolve_path(cwd)
        if isinstance(workdir, str):
            return workdir

        result = subprocess.run(
            args, shell=False, capture_output=True, text=True,
            timeout=timeout, cwd=workdir,
        )

        output = result.stdout
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"

        if output.strip():
            return output.strip()
        
        return success("Command executed successfully")
    except subprocess.TimeoutExpired as e:
        return handle_error(
            "run_command",
            e,
            f"command timed out after {timeout} seconds"
        )
    except FileNotFoundError as e:
        return handle_error(
            "run_command",
            e,
            f"command not found: {args[0]}"
        )
    except Exception as e:
        return handle_error(
            "run_command",
            e,
            "while executing command"
        )

def calculate(expression: str) -> str:
    """Evaluate a math expression."""
    try:
        result = eval(expression, {"__builtins__": {}}, {"abs": abs, "round": round, "int": int, "float": float, "min": min, "max": max, "sum": sum, "pow": pow, "sqrt": __import__("math").sqrt, "pi": __import__("math").pi})
        return str(result)
    except Exception as e:
        return f"Error: {e}"

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

def current_time(timezone: str = "UTC") -> str:
    """Get current date/time."""
    now = datetime.utcnow() if timezone == "UTC" else datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S") + f" ({timezone})"

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


def search_knowledge(query: str = "", k: int = 5) -> str:
    """Search knowledge documents using TF-IDF scoring. Returns ranked markdown snippets."""
    from pathlib import Path
    import os, re
    from micron.search import TFIDFIndex

    workdir = Path(os.getenv("MICRON_WORKDIR", os.getcwd()))
    knowledge_dir = workdir / "context" / "knowledge"
    if not knowledge_dir.exists():
        return "(knowledge directory not found)"

    # Load all markdown files
    texts: list[tuple[str, str]] = []
    for f in sorted(knowledge_dir.glob("*.md")):
        txt = f.read_text(errors="replace").strip()
        # Strip YAML frontmatter
        if txt.startswith("---"):
            parts = txt.split("---", 2)
            if len(parts) >= 3:
                txt = parts[2]
        # Remove title line
        txt = re.sub(r"^# .*$", "", txt, flags=re.MULTILINE)
        # Collapse whitespace + trim
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt and len(txt) > 5:
            texts.append((f.stem, txt))

    if not texts:
        return "(no knowledge documents)"

    if not query.strip():
        return "(no search query)"

    # Build TF-IDF index using shared class
    index = TFIDFIndex()
    for slug, text in texts:
        index.add(slug, text)

    # Search
    results = index.search(query, k=k)
    if not results:
        return "(no relevant knowledge)"

    # Format output
    out = []
    for slug, score in results:
        # Find matching snippet from the original text
        _, full = next(((s, t) for (ss, t) in texts if ss == slug), ("", ""))
        snippet = full[:300].replace("\n", " ").strip()
        out.append(f"[{slug}] (score: {score:.2f}) {snippet}...")

    return "\n".join(out)

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
    return f"Saved: {path}"


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

    path.write_text("\n".join(lines))
    return f"Created skill: {path.relative_to(workdir)}\nRun /reload to activate it."


# Core skills that cannot be overwritten
CORE_SKILLS = {"web_search", "fetch_url", "read_file", "write_file", "list_files",
               "run_command", "calculate", "python_eval", "current_time",
               "save_memory", "search_knowledge", "write_knowledge",
               "create_skill", "search_skill_library"}


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


def delete_file(path: str) -> str:
    """Delete a file from the working directory (moves to .trash/ for recovery).
    
    Args:
        path: Path to the file to delete (relative to workdir)
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success
    import shutil
    from datetime import datetime
    
    target = _resolve_path(path, must_exist=True)
    if isinstance(target, str):
        return target
    
    try:
        # Prevent deletion of directories
        if target.is_dir():
            return handle_error(
                "delete_file",
                Exception(f"Cannot delete directory '{path}'"),
                "use run_command with rm -rf to delete directories"
            )
        
        # Create .trash directory if it doesn't exist
        workdir = _get_workdir()
        trash_dir = workdir / ".trash"
        trash_dir.mkdir(exist_ok=True)
        
        # Generate unique trash name with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = target.name
        trash_name = f"{file_name}.{timestamp}"
        trash_path = trash_dir / trash_name
        
        # Move file to trash
        shutil.move(str(target), str(trash_path))
        
        return success(f"Deleted {file_name} (recoverable via /restore)")
    except Exception as e:
        return handle_error(
            "delete_file",
            e,
            f"while deleting {path}"
        )


def restore_file(filename: str) -> str:
    """Restore a file from .trash/ directory.
    
    Args:
        filename: Name of the file in .trash/ (from /trash listing)
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success
    import shutil
    
    workdir = _get_workdir()
    trash_dir = workdir / ".trash"
    
    if not trash_dir.exists():
        return handle_error(
            "restore_file",
            Exception("No trash directory found"),
            "no files have been deleted yet"
        )
    
    # Find the file in trash
    trash_path = trash_dir / filename
    if not trash_path.exists():
        # Try to find by original name (partial match)
        matches = list(trash_dir.glob(f"{filename}.*"))
        if len(matches) == 1:
            trash_path = matches[0]
        elif len(matches) > 1:
            # Multiple matches — list them
            names = [m.name for m in matches]
            return handle_error(
                "restore_file",
                Exception(f"Multiple files match '{filename}'"),
                f"found: {', '.join(names[:5])} — specify full name"
            )
        else:
            return handle_error(
                "restore_file",
                Exception(f"File '{filename}' not found in trash"),
                "use /trash to see available files"
            )
    
    # Determine restore location (original name without timestamp)
    original_name = trash_path.stem  # Remove .timestamp suffix
    restore_path = workdir / original_name
    
    # Handle name collision
    if restore_path.exists():
        # Add (1), (2), etc.
        counter = 1
        while restore_path.exists():
            stem = trash_path.stem.rsplit(".", 1)[0] if "." in trash_path.stem else trash_path.stem
            restore_path = workdir / f"{stem}({counter}){trash_path.suffix}"
            counter += 1
    
    try:
        shutil.move(str(trash_path), str(restore_path))
        return success(f"Restored to {restore_path.name}")
    except Exception as e:
        return handle_error(
            "restore_file",
            e,
            f"while restoring {filename}"
        )


def list_trash() -> str:
    """List files in .trash/ directory.
    
    Returns:
        List of trashed files with timestamps, or empty message
    """
    from micron.tools.error_handling import success
    
    workdir = _get_workdir()
    trash_dir = workdir / ".trash"
    
    if not trash_dir.exists():
        return success("Trash is empty (no files deleted yet)")
    
    files = sorted(trash_dir.iterdir())
    if not files:
        return success("Trash is empty")
    
    lines = ["🗑️ Trash:"]
    for f in files:
        if f.is_file():
            # Extract timestamp from filename
            parts = f.name.rsplit(".", 1)
            if len(parts) == 2 and len(parts[1]) == 15:  # YYYYMMDD_HHMMSS
                original_name = parts[0]
                timestamp = parts[1]
                # Format timestamp nicely
                try:
                    from datetime import datetime
                    dt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    time_str = timestamp
                lines.append(f"  {f.name}  ({original_name}, deleted {time_str})")
            else:
                lines.append(f"  {f.name}")
    
    return "\n".join(lines)


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
    import subprocess
    import shutil
    
    target = _resolve_path(path, must_exist=True)
    if isinstance(target, str):
        return target
    
    try:
        # Validate syntax before editing (best-effort — skip if subprocess unavailable)
        if path.endswith('.py'):
            try:
                compile_result = subprocess.run(
                    ["python3", "-m", "py_compile", str(target)],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if compile_result.returncode != 0 and compile_result.stderr:
                    return handle_error(
                        "edit_file",
                        Exception(f"Syntax error in {path}"),
                        f"before editing: {compile_result.stderr}"
                    )
            except (subprocess.TimeoutExpired, OSError):
                pass  # Skip validation if subprocess fails (resource limits)
        
        content = target.read_text(encoding="utf-8")
        
        # Check if old_text exists in file
        if old_text not in content:
            return handle_error(
                "edit_file",
                Exception(f"Text not found in {path}"),
                "the specified text to replace was not found"
            )
        
        # Create backup before editing
        bak_path = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(str(target), str(bak_path))
        
        new_content = content.replace(old_text, new_text)
        target.write_text(new_content, encoding="utf-8")
        
        # Validate syntax after editing (best-effort — skip if subprocess unavailable)
        if path.endswith('.py'):
            try:
                compile_result = subprocess.run(
                    ["python3", "-m", "py_compile", str(target)],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if compile_result.returncode != 0 and compile_result.stderr:
                    # Revert the edit if syntax error
                    shutil.copy2(str(bak_path), str(target))
                    return handle_error(
                        "edit_file",
                        Exception(f"Syntax error after editing {path}"),
                        compile_result.stderr
                    )
            except (subprocess.TimeoutExpired, OSError):
                pass  # Skip validation if subprocess fails (resource limits)
        
        return success(f"Edited {path} (replaced {len(old_text)} chars with {len(new_text)} chars)")
    except Exception as e:
        return handle_error(
            "edit_file",
            e,
            f"while editing {path}"
        )


def undo_file(path: str) -> str:
    """Restore a file from its .bak backup.
    
    Args:
        path: Path to the file to restore (relative to workdir)
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success
    import shutil
    
    target = _resolve_path(path, must_exist=False)
    if isinstance(target, str):
        # File doesn't exist, try to find .bak
        target = _get_workdir() / path
    
    bak_path = target.with_suffix(target.suffix + ".bak")
    
    if not bak_path.exists():
        return handle_error(
            "undo_file",
            Exception(f"No backup found for {path}"),
            "edit_file creates .bak backups automatically"
        )
    
    try:
        shutil.copy2(str(bak_path), str(target))
        # Remove the backup after successful restore
        bak_path.unlink()
        return success(f"Restored {path} from backup")
    except Exception as e:
        return handle_error(
            "undo_file",
            e,
            f"while restoring {path}"
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


# Tool registry for easy importing
TOOLS = {
    "web_search": web_search, "fetch_url": fetch_url, "read_file": read_file,
    "write_file": write_file, "paste_file": paste_file, "patch_file": patch_file,
    "list_files": list_files, "tree": tree, "run_command": run_command,
    "calculate": calculate, "python_eval": python_eval, "current_time": current_time,
    "save_memory": save_memory, "search_knowledge": search_knowledge,
    "write_knowledge": write_knowledge,
    "create_skill": create_skill, "search_skill_library": search_skill_library,
    "delete_file": delete_file,
    "restore_file": restore_file,
    "list_trash": list_trash,
    "edit_file": edit_file,
    "undo_file": undo_file,
    "list_skills": list_skills,
}