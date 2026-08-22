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


def test_wikilink_strip(tmp_path: Path):
    kd = tmp_path / "knowledge"
    kd.mkdir()
    (kd / "note.md").write_text("See [[OtherNote]] and [[OtherNote|alias]] and ![[embed.png]] here")
    ki = KnowledgeIndex(kd)
    ki.reload()
    parsed = ki.get("note")
    assert parsed is not None
    assert "[[" not in parsed
    assert "]]" not in parsed
    assert "OtherNote" in parsed
    assert "alias" in parsed
    assert "embed.png" in parsed
    # search still finds alias text
    hits = ki.search("alias")
    assert len(hits) == 1


def test_subfolder_glob(tmp_path: Path):
    kd = tmp_path / "knowledge"
    sub = kd / "sub"
    sub.mkdir(parents=True)
    (kd / "top.md").write_text("python top")
    (sub / "nested.md").write_text("python nested deep")
    ki = KnowledgeIndex(kd)
    assert ki.size == 2
    hits = ki.search("python")
    slugs = {h.slug for h in hits}
    assert "top" in slugs
    assert "nested" in slugs


def test_env_overrides_context(tmp_path: Path, monkeypatch):
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "knowledge").mkdir()
    (ctx / "knowledge" / "a.md").write_text("hello from ctx")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "b.md").write_text("hello from vault python")
    # vault via MICRON_KNOWLEDGE_DIR should win over context
    monkeypatch.setenv("MICRON_KNOWLEDGE_DIR", str(vault))
    monkeypatch.setenv("MICRON_CONTEXT_DIR", str(ctx))
    ki = KnowledgeIndex()  # no explicit path — env wins
    assert ki._dir == vault.resolve()
    assert ki.size == 1
    assert ki.search("vault")[0].slug == "b"
    # cache should live in context, not vault
    assert ki._cache_dir == ctx.resolve()
    assert not (vault / ".knowledge_index.json").exists()
    # explicit kill vault -> fallback to ctx/knowledge
    monkeypatch.delenv("MICRON_KNOWLEDGE_DIR")
    ki2 = KnowledgeIndex()
    assert ki2._dir == (ctx / "knowledge").resolve()


def test_symlink_vault(tmp_path: Path, monkeypatch):
    real = tmp_path / "real_vault"
    real.mkdir()
    (real / "note.md").write_text("python symlink")
    link = tmp_path / "vault_link"
    link.symlink_to(real)
    monkeypatch.setenv("MICRON_KNOWLEDGE_DIR", str(link))
    ki = KnowledgeIndex()
    assert ki._dir == real.resolve()  # resolves symlink
    assert ki.size == 1
