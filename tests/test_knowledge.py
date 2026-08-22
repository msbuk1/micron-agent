import pathlib
import tempfile
from pathlib import Path

from micron.knowledge import KnowledgeIndex


def test_prompt_context_ranks_and_budgets(tmp_path: Path):
    kd = tmp_path / "knowledge"
    kd.mkdir()
    (kd / "a.md").write_text("---\nname: a\n---\n# Title\nPython async helps concurrency")
    (kd / "b.md").write_text("# B\nCooking recipes")
    (kd / "c.md").write_text("---\nname: c\n---\nPython threads")
    ki = KnowledgeIndex(kd)
    block = ki.prompt_context("python concurrency")
    assert "async" in block
    assert "Cooking" not in block


def test_search_formats(tmp_path: Path):
    kd = tmp_path / "knowledge"
    kd.mkdir()
    (kd / "x.md").write_text("hello world python")
    ki = KnowledgeIndex(kd)
    hits = ki.search("python", k=1)
    assert len(hits) == 1
    assert hits[0].slug == "x"
    assert hits[0].score > 0
    assert "hello" in hits[0].snippet

    # no relevant
    assert ki.prompt_context("nonexistentxyz") == "(no relevant knowledge)"
    assert ki.search("nonexistentxyz") == []


def test_reload_after_write(tmp_path: Path):
    kd = tmp_path / "knowledge"
    kd.mkdir()
    (kd / "a.md").write_text("hello python world")
    ki = KnowledgeIndex(kd)
    assert ki.size == 1
    (kd / "b.md").write_text("hello again python")
    ki.reload()
    assert ki.size == 2
    assert len(ki.search("python")) == 2


def test_sentinels(tmp_path: Path):
    # missing dir
    ki = KnowledgeIndex(tmp_path / "missing")
    assert ki.prompt_context("hi") == "(no knowledge files loaded)"
    assert ki.search("hi") == []
    assert ki.size == 0
    # empty dir
    kd = tmp_path / "empty"
    kd.mkdir()
    ki2 = KnowledgeIndex(kd)
    assert ki2.prompt_context("hi") == "(no knowledge files loaded)"
