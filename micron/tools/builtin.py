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

def run_command(cmd: str, cwd: str = ".", timeout: int = 30) -> str:
    """Run a shell command and return its output.
    
    Args:
        cmd: Shell command to execute
        cwd: Working directory (relative to workdir)
        timeout: Maximum execution time in seconds
        
    Returns:
        Command output or error message
    """
    from micron.tools.error_handling import handle_error, format_tool_result, success
    import re
    
    # Restrict mode. If MICRON_UNRESTRICTED=1, only block truly destructive patterns.
    unrestricted = os.getenv("MICRON_UNRESTRICTED", "").lower() in ("1", "true", "yes")

    # Improved command blocklist with regex patterns
    denied_patterns = [
        r":\(\)\{",  # Fork bomb pattern
        r"fork\s+bomb",  # Fork bomb
        r"chmod\s+-R\s+777",  # Recursive chmod 777
        r">\s*/dev/sd",  # Redirect to block device
    ]
    
    if not unrestricted:
        # Dangerous commands that should always be blocked
        denied_patterns.extend([
            r"rm\s+-rf\b",  # rm -rf (recursive delete)
            r"mkfs\b",  # mkfs (format filesystem)
            r"dd\s+if=",  # dd with input file
            r"sudo\s+su\b",  # sudo su
            r"sudo\s+sh\b",  # sudo sh
            r"sudo\s+bash\b",  # sudo bash
            r"chmod\s+777",  # chmod 777
            r"chown\s+.*:.*",  # chown to arbitrary user
            r"\|\s*bash\b",  # pipe to bash
            r"\|\s*sh\b",  # pipe to sh
            r"\|\s*zsh\b",  # pipe to zsh
            r"wget\s+.*\|\s*bash",  # wget | bash
            r"curl\s+.*\|\s*bash",  # curl | bash
            r"wget\s+.*\|\s*sh",  # wget | sh
            r"curl\s+.*\|\s*sh",  # curl | sh
            r"wget\s+.*\|\s*zsh",  # wget | zsh
            r"curl\s+.*\|\s*zsh",  # curl | zsh
            r"\.\s*/",  # Relative path execution (./malicious.sh)
            r"~/",  # Home directory execution
            r"\$\(",  # Command substitution
            r"`.*`",  # Backtick command substitution
            r"apt-get\s+install",  # Package installation
            r"yum\s+install",  # Package installation
            r"pacman\s+-Sy",  # Package installation
            r"chsh",  # Change shell
            r"useradd\b",  # Add user
            r"userdel\b",  # Delete user
            r"passwd",  # Change password
            r"mv\s+/.*",  # Move to root
            r"cp\s+/.*",  # Copy to root
        ])

    cmd_lower = cmd.lower().strip()
    
    # Check for dangerous patterns using regex
    for pattern in denied_patterns:
        if re.search(pattern, cmd_lower):
            return handle_error(
                "run_command",
                Exception(f"Command blocked: dangerous pattern detected"),
                f"blocked command containing '{pattern}'"
            )

    # Additional safety checks
    _set_command_resource_limits()
    if len(cmd) > 500:
        return handle_error(
            "run_command",
            Exception("Command too long"),
            "command exceeds 500 character limit"
        )

    try:
        workdir = _resolve_path(cwd)
        if isinstance(workdir, str):
            return workdir

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
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

    def tokenize(t: str) -> list[str]:
        return re.findall(r"\b\w+\b", t.lower())

    # Build TF-IDF index directly from knowledge documents
    tokens_per_doc = [Counter(tokenize(text)) for _, text in texts]
    vocab = set(t for toks in tokens_per_doc for t in toks)
    n_docs = len(texts)
    
    # Calculate IDF
    idf = {}
    for term in vocab:
        df = sum(1 for toks in tokens_per_doc if term in toks)
        idf[term] = math.log(n_docs / (df + 1)) + 1.0

    query_tokens = Counter(tokenize(query))
    if not query_tokens:
        return "(no search query)"

    # Score documents
    scored = []
    for (slug, _), toks in zip(texts, tokens_per_doc):
        score = sum(toks.get(t, 0) * idf.get(t, 0) for t in query_tokens) / (sum(toks.values()) + 1)
        scored.append((score, slug))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, slug in scored[:k]:
        if score <= 0:
            continue
        # Find matching snippet from the original text
        _, full = next(((s, t) for (ss, t) in texts if ss == slug), ("", ""))
        snippet = full[:300].replace("\n", " ").strip()
        out.append(f"[{slug}] (score: {score:.2f}) {snippet}...")

    return "\n".join(out) if out else "(no relevant knowledge)"

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
    """Delete a file from the working directory.
    
    Args:
        path: Path to the file to delete (relative to workdir)
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success
    
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
        
        # Store file info for potential recovery
        file_name = target.name
        file_path = str(target)
        
        target.unlink()
        return success(f"Deleted {file_name}")
    except Exception as e:
        return handle_error(
            "delete_file",
            e,
            f"while deleting {path}"
        )


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Edit a file by replacing old_text with new_text.
    
    Args:
        path: Path to the file (relative to workdir)
        old_text: Text to replace
        new_text: Replacement text
        
    Returns:
        Success message or error
    """
    from micron.tools.error_handling import handle_error, success
    import subprocess
    
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
                    target.write_text(content, encoding="utf-8")
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
    "write_file": write_file, "list_files": list_files, "run_command": run_command,
    "calculate": calculate, "python_eval": python_eval, "current_time": current_time,
    "save_memory": save_memory, "search_knowledge": search_knowledge,
    "write_knowledge": write_knowledge,
    "create_skill": create_skill, "search_skill_library": search_skill_library,
    "delete_file": delete_file,
    "edit_file": edit_file,
    "list_skills": list_skills,
}