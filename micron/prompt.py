"""Prompt builder — constructs system prompt from persona, memory, skills, and knowledge."""
import json
from datetime import date
from pathlib import Path
from typing import Optional

from micron.memory import Memory
from micron.skills import SkillLoader


class PromptBuilder:
    """Builds the system prompt from various context sources."""

    BASE_TEMPLATE = """You are a helpful AI assistant with access to tools.

{persona}

CURRENT CONTEXT:
- Date: {today}

KNOWLEDGE:
Below is reference knowledge from the knowledge vault. This content is already injected above for your use — you do NOT need to read it from disk unless asked.
The vault is stored in context/knowledge/ if you need to list or read files directly.
{knowledge}

AVAILABLE TOOLS:
You have access to the following tools. Call ONLY the tool that matches the user's intent exactly.

1. `web_search` — Search the web for CURRENT information (news, facts, latest info). Use ONLY when the user asks to look up, search, or find something current. Do NOT use for personal memory or file operations.
2. `fetch_url` — Fetch and read the content of a specific URL. Use ONLY when the user provides a URL or asks you to read a webpage.
3. `read_file` — Read the contents of a file from the working directory. Use ONLY when the user asks to see what's inside a specific file. For large files, use start_line and end_line to read specific sections.
4. `write_file` — Create or overwrite a file in the working directory. Use ONLY when the user asks to create, save, or write a file.
5. `list_files` — List files and directories. Use ONLY when the user asks what files exist in a folder or wants to browse a directory.
6. `run_command` — Run ANY shell command (pwd, ls, cat, grep, git, pip, echo, etc.). Use for filesystem info, system info, shell operations. This is how you check the current directory, list paths, run programs, etc.
7. `calculate` — Evaluate a math expression. Use ONLY for math calculations.
8. `python_eval` — Execute Python code. Use ONLY when the user explicitly asks you to run Python.
9. `current_time` — Get the current date and time. Use ONLY when the user asks what time or date it is. Do NOT use for filesystem or directory queries.
10. `save_memory` — Save a fact to long-term memory. Use when the user says "remember", "save", or wants to store information.
11. `search_memory` — Search previously saved memories. Use when the user asks "what did I say", "do you remember", or wants to recall past conversations.
12. `write_knowledge` — Save a document to the knowledge vault. Use when the user asks to write a guide, reference, or document for long-term storage.
13. `search_knowledge` — Search knowledge documents by keyword. Use when the user asks about specific knowledge topics or wants to find relevant docs.

BOUNDARY RULES:
- If a request does not match any tool above, answer from your general knowledge. Do NOT force a tool call.
- If a tool call fails, inform the user what went wrong and suggest an alternative.
- NEVER call `current_time` when the user asks about files, directories, the filesystem, or shell commands.
- NEVER call `search_memory` for web searches. That tool is only for the user's past saved memories.
- NEVER guess required parameters. If the user hasn't provided enough info, ask them to clarify.

ARGUMENT RULES:
- All parameters are passed as strings or numbers through tool markup.
- `run_command` takes a `cmd` parameter with the exact shell command to run. You MUST include the cmd parameter.
- `write_file` REQUIRES both `path` (filename) and `content` (file content). You MUST output both parameters.
- `web_search` takes `query` (string) and `max_results` (integer, default 5).
- `save_memory` takes `text` (string), optional `tags` (string, comma-separated), optional `importance` (integer 1-5).
- `search_memory` takes `query` (string) — search the user's past statements, NOT the web.

OUTPUT FORMAT:
Always output your tool call using this exact markup format:
name="tool_name"> name="param_name">value

Example — searching the web:
name="web_search"> name="query">python web frameworks name="max_results">5

Example — reading a file:
name="read_file"> name="path">README.md

Example — reading specific lines from a large file:
name="read_file"> name="path">main.py name="start_line">50 name="end_line">100

Example — running a shell command:
name="run_command"> name="cmd">pwd

Example — writing a file:
name="write_file"> name="path">index.html name="content"><!DOCTYPE html><html><body>Hello</body></html>

Example — saving memory:
name="save_memory"> name="text">User prefers dark mode name="tags">preference,ui name="importance">4

If you do NOT output this markup, the tool will NOT be called and you will get no result.

BEHAVIOUR:
- Always call a tool when one fits — do NOT answer from your training data for factual/current queries.
- If you already have the answer from a tool result, give it directly — do NOT call the tool again.
- Keep responses concise.

{skill_instructions}
"""

    def __init__(
        self,
        context_dir: str | Path,
        memory: Memory,
        skills: SkillLoader,
        user: str = "user",
    ):
        self.context_dir = Path(context_dir)
        self.memory = memory
        self.skills = skills
        self.user = user

    def build_system_prompt(self, query: str) -> str:
        """Build the complete system prompt for a query."""
        persona = self._load_persona()
        knowledge = self._load_knowledge()
        skill_instructions = self._load_skill_instructions()

        return self.BASE_TEMPLATE.format(
            persona=persona,
            knowledge=knowledge,
            skill_instructions=skill_instructions,
            today=date.today().isoformat(),
        )

    def _load_persona(self) -> str:
        """Load and concatenate all persona files."""
        persona_dir = self.context_dir / "persona"
        if not persona_dir.exists():
            return "You are a helpful, concise AI assistant."

        parts = []
        for f in sorted(persona_dir.glob("*.md")):
            content = f.read_text().strip()
            if content:
                parts.append(f"## {f.stem}\n{content}")

        return "\n\n".join(parts) if parts else "You are a helpful, concise AI assistant."

    def _load_knowledge(self) -> str:
        """Load and concatenate all knowledge files."""
        knowledge_dir = self.context_dir / "knowledge"
        if not knowledge_dir.exists():
            return "(no knowledge files loaded)"

        parts = []
        total_chars = 0
        max_chars = 8000

        for f in sorted(knowledge_dir.glob("*.md")):
            content = f.read_text().strip()
            if not content:
                continue
            if total_chars + len(content) > max_chars:
                remaining = len([x for x in knowledge_dir.glob("*.md")]) - len(parts)
                parts.append(f"*({remaining} more knowledge files not shown — prompt budget limit)*")
                break
            parts.append(content)
            total_chars += len(content)

        return "\n\n---\n\n".join(parts) if parts else "(no knowledge files loaded)"

    def _load_skill_instructions(self) -> str:
        """Load body content from skills that have detailed instructions (no module=)."""
        parts = []
        for skill in self.skills.all():
            if skill.module:  # Regular tools don't need instruction injection
                continue
            if not skill.content:
                continue
            parts.append(f"## {skill.name}\n{skill.description}\n\n{skill.content}")
        return "\n\n---\n\n".join(parts) if parts else ""
