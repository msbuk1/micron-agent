"""Tests for micron skills module."""
import tempfile
from pathlib import Path

from micron.skills import SkillLoader


def test_skill_loader_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = SkillLoader(Path(tmpdir))
        skills = loader.load_all()
        assert len(skills) == 0
        assert loader.schemas() == []


def test_skill_loader_loads_skill():
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_file = Path(tmpdir) / "test_skill.md"
        skill_file.write_text("""---
name: test_skill
description: A test skill
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    query:
      type: string
      description: Test query
---
""")
        loader = SkillLoader(Path(tmpdir))
        skills = loader.load_all()
        
        assert len(skills) == 1
        assert "test_skill" in skills
        
        skill = skills["test_skill"]
        assert skill.name == "test_skill"
        assert skill.description == "A test skill"
        assert skill.write is False
        assert skill.module == "micron.tools.builtin"
        assert skill.parameters["type"] == "object"
        assert "query" in skill.parameters["properties"]


def test_skill_schema_format():
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_file = Path(tmpdir) / "test_skill.md"
        skill_file.write_text("""---
name: test_skill
description: A test skill
write: false
parameters:
  type: object
  properties:
    query:
      type: string
---
""")
        loader = SkillLoader(Path(tmpdir))
        loader.load_all()
        schemas = loader.schemas()
        
        assert len(schemas) == 1
        schema = schemas[0]
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test_skill"
        assert schema["function"]["description"] == "A test skill"
        assert schema["function"]["parameters"]["type"] == "object"


def test_skill_write_flag():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Skill without write (default)
        skill1_file = Path(tmpdir) / "read_skill.md"
        skill1_file.write_text("""---
name: read_skill
description: A read-only skill
write: false
parameters:
  type: object
  properties: {}
---
""")
        # Skill with write
        skill2_file = Path(tmpdir) / "write_skill.md"
        skill2_file.write_text("""---
name: write_skill
description: A write skill
write: true
parameters:
  type: object
  properties: {}
---
""")
        loader = SkillLoader(Path(tmpdir))
        skills = loader.load_all()
        
        assert skills["read_skill"].write is False
        assert skills["write_skill"].write is True


if __name__ == "__main__":
    test_skill_loader_empty()
    test_skill_loader_loads_skill()
    test_skill_schema_format()
    test_skill_write_flag()
    print("All skills tests passed!")