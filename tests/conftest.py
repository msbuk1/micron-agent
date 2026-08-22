import pytest
from pathlib import Path
from micron.memory import Memory


@pytest.fixture
def memory_factory(tmp_path: Path):
    """Factory yielding isolated Memory(tmp_path) — auto-cleans after test.

    Usage:
        def test_something(memory_factory):
            mem = memory_factory(tags=["test"])  # or memory_factory()
            mid = mem.add("test memory", tags=["test"])
            # ... assert ...
            # auto-cleaned: deletes any `tags=["test"]` or text=="test memory" left behind

    Isolation: never touches `context/memory/memories.jsonl`.
    """
    created: list[Memory] = []

    def _make(tags=None, **kw) -> Memory:
        mem = Memory(tmp_path / f"mem-{len(created)}", **kw)
        created.append(mem)
        return mem

    yield _make

    # Teardown: sweep test-tagged entries if test forgot to delete
    for mem in created:
        try:
            for m in list(mem.list(n=100)):
                if m.text == "test memory" or "test" in (m.tags or []):
                    mem.delete(m.id)
        except Exception:
            pass


@pytest.fixture
def memory_tmp(tmp_path: Path):
    """Simple isolated Memory(tmp_path) fixture."""
    return Memory(tmp_path)
