"""Tests for Hermes-style procedure skill loading."""
import pytest
from pathlib import Path
import tempfile
import os

from micron.skills import SkillLoader


@pytest.fixture
def skills_dir():
    """Create a temp skills directory with a procedure skill."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a procedure skill directory
        skill_dir = Path(tmpdir) / "my-procedure"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-procedure\ndescription: A test procedure skill\n---\n\n# My Procedure\n\nDo these steps:\n\n1. First step\n2. Second step\n\nSee [guide.md](guide.md) for details.\n"
        )
        (skill_dir / "guide.md").write_text("# Guide\n\nDetailed guide content here.")
        yield Path(tmpdir)


class TestProcedureSkills:
    """Tests for procedure skill loading."""

    def test_loads_procedure_skill(self, skills_dir):
        """Test that directory-based skills are loaded."""
        loader = SkillLoader(skills_dir)
        skills = loader.load_all()
        assert "my-procedure" in skills

    def test_procedure_flag(self, skills_dir):
        """Test that procedure skills have procedure=True."""
        loader = SkillLoader(skills_dir)
        skills = loader.load_all()
        skill = skills["my-procedure"]
        assert skill.procedure is True

    def test_no_module(self, skills_dir):
        """Test that procedure skills have no module."""
        loader = SkillLoader(skills_dir)
        skills = loader.load_all()
        skill = skills["my-procedure"]
        assert skill.module is None

    def test_linked_files_resolved(self, skills_dir):
        """Test that linked .md files are inlined."""
        loader = SkillLoader(skills_dir)
        skills = loader.load_all()
        skill = skills["my-procedure"]
        assert "guide.md" in skill.linked_files
        assert "Detailed guide content" in skill.content

    def test_excluded_from_schemas(self, skills_dir):
        """Test that procedure skills don't appear in tool schemas."""
        loader = SkillLoader(skills_dir)
        loader.load_all()
        schemas = loader.schemas()
        names = [s["function"]["name"] for s in schemas]
        assert "my-procedure" not in names

    def test_flat_skill_still_works(self, skills_dir):
        """Test that flat .md skills still load alongside procedure skills."""
        (skills_dir / "flat-tool.md").write_text(
            "---\nname: flat-tool\ndescription: A flat tool\nmodule: some.module\nwrite: false\n---\n"
        )
        loader = SkillLoader(skills_dir)
        skills = loader.load_all()
        assert "flat-tool" in skills
        assert skills["flat-tool"].procedure is False
        assert skills["flat-tool"].module == "some.module"
