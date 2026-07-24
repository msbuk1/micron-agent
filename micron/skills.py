"""Skill loader — loads Markdown skills with YAML frontmatter."""
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    name: str
    description: str
    parameters: dict
    write: bool
    module: str | None = None
    source_file: Path | None = None
    content: str = ""  # Body content after frontmatter
    procedure: bool = False  # True for Hermes-style procedure skills
    linked_files: dict[str, str] = field(default_factory=dict)  # name → content

    @property
    def openai_schema(self) -> dict:
        """Return OpenAI-compatible function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class SkillLoader:
    """Loads skills from Markdown files with YAML frontmatter."""

    FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._skills: dict[str, Skill] = {}

    def load_all(self) -> dict[str, Skill]:
        """Load all skills from the skills directory."""
        self._skills = {}
        # Flat .md files (micron tool/knowledge skills)
        for f in self.skills_dir.glob("*.md"):
            try:
                skill = self._load_skill(f)
                if skill:
                    self._skills[skill.name] = skill
            except Exception as e:
                print(f"[WARN] Failed to load skill {f}: {e}")
        # Directory-based skills (Hermes-style procedure skills)
        for d in self.skills_dir.iterdir():
            if d.is_dir() and (d / "SKILL.md").exists():
                try:
                    skill = self._load_procedure_skill(d)
                    if skill and skill.name not in self._skills:
                        self._skills[skill.name] = skill
                except Exception as e:
                    print(f"[WARN] Failed to load procedure skill {d}: {e}")
        return self._skills

    def _load_skill(self, path: Path) -> Skill | None:
        content = path.read_text()
        match = self.FRONTMATTER_PATTERN.match(content)
        if not match:
            return None

        frontmatter = yaml.safe_load(match.group(1))
        if not frontmatter or "name" not in frontmatter:
            return None

        # Body content = everything after the closing ---
        body = content[match.end():].strip()

        return Skill(
            name=frontmatter["name"],
            description=frontmatter.get("description", ""),
            parameters=frontmatter.get("parameters", {"type": "object", "properties": {}}),
            write=frontmatter.get("write", False),
            module=frontmatter.get("module"),
            source_file=path,
            content=body,
        )

    def _load_procedure_skill(self, skill_dir: Path) -> Skill | None:
        """Load a Hermes-style procedure skill from a directory.

        Expects <skill_dir>/SKILL.md with YAML frontmatter.
        Resolves linked .md files in the body and inlines their content.
        """
        skill_md = skill_dir / "SKILL.md"
        content = skill_md.read_text()
        match = self.FRONTMATTER_PATTERN.match(content)
        if not match:
            return None

        frontmatter = yaml.safe_load(match.group(1))
        if not frontmatter or "name" not in frontmatter:
            return None

        body = content[match.end():].strip()

        # Resolve linked files: [name](name.md) → inline content
        linked_files = {}
        for link_match in re.finditer(r"\[([^\]]+)\]\(([^)]+\.md)\)", body):
            link_name = link_match.group(2)
            link_path = skill_dir / link_name
            if link_path.exists():
                linked_files[link_name] = link_path.read_text()

        # Inline linked file content at the end of the body
        if linked_files:
            parts = [body]
            for fname, fcontent in linked_files.items():
                parts.append(f"\n\n---\n\n## {fname}\n\n{fcontent}")
            body = "\n".join(parts)

        return Skill(
            name=frontmatter["name"],
            description=frontmatter.get("description", ""),
            parameters={"type": "object", "properties": {}},
            write=False,
            source_file=skill_md,
            content=body,
            procedure=True,
            linked_files=linked_files,
        )

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def schemas(self) -> list[dict]:
        """Return tool schemas in OpenAI format (excludes procedure skills)."""
        return [s.openai_schema for s in self._skills.values() if not s.procedure]

    def reload(self):
        """Reload all skills."""
        self.load_all()

    def add_plugin(self, td) -> Skill:
        """Add a plugin tool as a synthetic Skill.

        Args:
            td: A ToolDescriptor from the plugin system.

        Returns:
            The newly created Skill, or the existing one if a skill with
            the same name already exists.
        """
        if td.name in self._skills:
            return self._skills[td.name]

        skill = Skill(
            name=td.name,
            description=td.description,
            parameters=td.parameters or {"type": "object", "properties": {}},
            write=td.write,
            module=None,
            content=f"Plugin tool: {td.description}",
        )
        self._skills[td.name] = skill
        return skill