"""Prompt builder — constructs system prompt from persona, memory, skills, and knowledge."""
import json
from datetime import date
from pathlib import Path
from typing import Optional

from micron.memory import Memory
from micron.skills import SkillLoader


class PromptBuilder:
    """Builds the system prompt from various context sources."""

    BASE_TEMPLATE = """You are micron, a lightweight AI assistant with access to tools and memory.

{persona}

CURRENT CONTEXT:
- Date: {today}

MEMORY (relevant entries):
{memory}

KNOWLEDGE (relevant documents):
{knowledge}

AVAILABLE TOOLS:
{tools}

INSTRUCTIONS:
- Use a tool only when the user's request clearly requires it.
- Call tools using the function-calling protocol provided by your model endpoint.
- Tools marked with [WRITE] require user confirmation before execution.
- Do not guess required parameters; ask for clarification if info is missing.
- Do not call a tool again if the result has already been returned to you.
- Keep responses concise unless asked for detail.
{text_tool_format}
"""

    TEXT_TOOL_FORMAT = """OUTPUT FORMAT (text-based model):
When you need a tool, output exactly:
<function name="TOOL_NAME">{"arg": "value"}</function>
Tool results will be provided in the next message."""

    def __init__(
        self,
        context_dir: str | Path,
        memory: Memory,
        skills: SkillLoader,
        user: str = "user",
        use_text_tool_format: bool = False,
    ):
        self.context_dir = Path(context_dir)
        self.memory = memory
        self.skills = skills
        self.user = user
        self.use_text_tool_format = use_text_tool_format

    def build_system_prompt(self, query: str) -> str:
        """Build the complete system prompt for a query."""
        persona = self._load_persona()
        memory = self._load_memory(query)
        knowledge = self._load_knowledge(query)
        tools = self._load_tools()
        skill_instructions = self._load_skill_instructions()
        text_tool_format = self.TEXT_TOOL_FORMAT if self.use_text_tool_format else ""

        if skill_instructions:
            tools += "\n\n---\n\n" + skill_instructions

        return self.BASE_TEMPLATE.format(
            persona=persona,
            memory=memory,
            knowledge=knowledge,
            tools=tools,
            today=date.today().isoformat(),
            text_tool_format=text_tool_format,
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

    def _load_memory(self, query: str = "") -> str:
        """Load relevant memory entries."""
        entries = self.memory.search(query, k=5)
        if not entries:
            return "(no relevant memories)"
        lines = []
        for e in entries:
            tags = " ".join(f"#{t}" for t in e.tags) if e.tags else ""
            lines.append(f"- [{e.timestamp[:10]}] {e.text} {tags}")
        return "\n".join(lines)

    def _load_tools(self) -> str:
        """Generate tool description list dynamically from loaded skills."""
        if not self.skills.all():
            return "(no tools available)"
        lines = []
        for skill in self.skills.all():
            marker = " [WRITE]" if skill.write else ""
            params = skill.parameters.get("properties", {})
            if params:
                param_desc = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in params.items())
            else:
                param_desc = "no parameters"
            lines.append(f"- {skill.name}{marker}: {skill.description} ({param_desc})")
        return "\n".join(lines)

    def _load_knowledge(self, query: str = "") -> str:
        """Load knowledge files, filtered by query relevance if provided."""
        knowledge_dir = self.context_dir / "knowledge"
        if not knowledge_dir.exists():
            return "(no knowledge files loaded)"

        files = sorted(knowledge_dir.glob("*.md"))
        if not files:
            return "(no knowledge files loaded)"

        # If query provided, score and filter files
        if query:
            query_words = set(query.lower().split())
            scored = []
            for f in files:
                try:
                    content = f.read_text().strip()
                    if not content:
                        continue
                    content_lower = content.lower()
                    score = sum(1 for word in query_words if word in content_lower)
                    scored.append((score, f, content))
                except Exception:
                    continue
            scored.sort(key=lambda x: x[0], reverse=True)
            files_with_content = [(f, c) for s, f, c in scored if s > 0]
            if not files_with_content:
                return "(no relevant knowledge)"
        else:
            files_with_content = [(f, f.read_text().strip()) for f in files if f.read_text().strip()]

        if not files_with_content:
            return "(no relevant knowledge)"

        parts = []
        total_chars = 0
        max_chars = 8000

        for f, content in files_with_content:
            if not content:
                continue
            if total_chars + len(content) > max_chars:
                remaining = len(files_with_content) - len(parts)
                if remaining > 0:
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
