"""Tests for micron memory module."""
import tempfile
from pathlib import Path

from micron.memory import Memory


def test_memory_add_and_list():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = Memory(Path(tmpdir))
        mid = mem.add("Test memory entry", tags=["test"], importance=5)
        assert mid is not None
        assert len(mid) == 12  # UUID short form
        
        memories = mem.list(n=10)
        assert len(memories) == 1
        assert memories[0].text == "Test memory entry"
        assert memories[0].tags == ["test"]
        assert memories[0].importance == 5


def test_memory_search():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = Memory(Path(tmpdir))
        mem.add("User prefers dark mode", tags=["preference", "ui"], importance=3)
        mem.add("User likes Python", tags=["preference", "language"], importance=4)
        mem.add("Random fact about cats", tags=["animal"], importance=1)
        
        results = mem.search("dark mode", k=5)
        assert len(results) == 1
        assert "dark mode" in results[0].text.lower()
        
        results = mem.search("user", k=5)
        assert len(results) == 2
        
        results = mem.search("cats", k=5)
        assert len(results) == 1
        assert "cats" in results[0].text.lower()


def test_memory_search_with_tags():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = Memory(Path(tmpdir))
        # Add extra document to make TF-IDF work with multiple docs
        mem.add("Extra context", tags=["other"], importance=3)
        mem.add("Dark mode preference", tags=["preference", "ui"], importance=3)
        mem.add("Python preference", tags=["preference", "language"], importance=4)
        
        results = mem.search("preference", k=5, tags=["ui"])
        assert len(results) == 1
        assert results[0].tags == ["preference", "ui"]
        
        results = mem.search("preference", k=5, tags=["language"])
        assert len(results) == 1
        assert results[0].tags == ["preference", "language"]


def test_memory_importance_scoring():
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = Memory(Path(tmpdir))
        # Add extra document to make TF-IDF work with multiple docs
        mem.add("Another context", tags=["other"], importance=3)
        mem.add("Low importance", tags=["test"], importance=1)
        mem.add("High importance", tags=["test"], importance=5)
        
        results = mem.search("importance", k=5)
        # High importance should rank higher (assuming time is similar)
        assert len(results) >= 2
        assert results[0].text == "High importance"
        assert results[1].text == "Low importance"


if __name__ == "__main__":
    test_memory_add_and_list()
    test_memory_search()
    test_memory_search_with_tags()
    test_memory_importance_scoring()
    print("All memory tests passed!")