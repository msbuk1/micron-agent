"""Skill loader — loads Markdown skills with YAML frontmatter."""
import re
import yaml
from dataclasses import dataclass
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
        for f in self.skills_dir.glob("*.md"):
            try:
                skill = self._load_skill(f)
                if skill:
                    self._skills[skill.name] = skill
            except Exception as e:
                print(f"[WARN] Failed to load skill {f}: {e}")
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

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def schemas(self) -> list[dict]:
        """Return all skill schemas in OpenAI format."""
        return [s.openai_schema for s in self._skills.values()]

    def reload(self):
        """Reload all skills."""
        self.load_all()