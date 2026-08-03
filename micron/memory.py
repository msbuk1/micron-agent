"""File-based memory with TF-IDF search — pure Python, zero deps.

Adapted from agent-memory-lite (MIT license).
"""
import datetime
import json
import math
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from micron.search import TFIDFIndex, tokenize


@dataclass
class MemoryEntry:
    id: str
    timestamp: str
    text: str
    tags: list[str]
    importance: int
    metadata: dict


class Memory:
    """JSONL-backed memory with TF-IDF keyword search."""

    def __init__(
        self,
        store_path: str | Path,
        time_decay_lambda: float = 0.01,
        max_results: int = 10,
    ):
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.memories_file = self.store_path / "memories.jsonl"
        self.time_decay_lambda = time_decay_lambda
        self.max_results = max_results

        # TF-IDF index (shared) — acts as the sole document store now: each
        # entry is added alongside its text via `add(id, text, doc=entry)`.
        self._index = TFIDFIndex()
        self._dirty = True

    def _load(self) -> list[MemoryEntry]:
        if not self.memories_file.exists():
            return []
        entries = []
        for line in self.memories_file.read_text().strip().splitlines():
            if not line:
                continue
            try:
                data = json.loads(line)
                entries.append(MemoryEntry(**data))
            except (json.JSONDecodeError, TypeError):
                continue
        return entries

    def _save_all(self, entries: list[MemoryEntry]):
        self.memories_file.write_text(
            "\n".join(json.dumps(e.__dict__) for e in entries) + "\n"
        )

    def _rebuild_index(self):
        self._index.clear()
        for entry in self._load():
            self._index.add(entry.id, entry.text, doc=entry)
        self._dirty = False

    def _all(self) -> dict[str, MemoryEntry]:
        """Return all entries keyed by id (the index is the sole store)."""
        if self._dirty:
            self._rebuild_index()
        return self._index.docs()

    def _score(self, query: str, doc: MemoryEntry) -> float:
        # Base TF-IDF score from shared index
        score = self._index.score(query, doc.id)
        if score == 0:
            return 0.0

        # Time decay
        try:
            ts = time.mktime(time.strptime(doc.timestamp[:19], "%Y-%m-%dT%H:%M:%S"))
            days_old = (time.time() - ts) / 86400
            time_factor = math.exp(-self.time_decay_lambda * days_old)
        except (ValueError, OverflowError):
            time_factor = 1.0

        # Importance boost
        imp_factor = 1.0 + (doc.importance - 3) * 0.15

        return score * time_factor * imp_factor

    def add(
        self,
        text: str,
        tags: list[str] | None = None,
        importance: int = 3,
        metadata: dict | None = None,
    ) -> str:
        """Add a memory entry."""
        entry = MemoryEntry(
            id=uuid.uuid4().hex[:12],
            timestamp=datetime.datetime.now().isoformat(),
            text=text,
            tags=tags or [],
            importance=max(1, min(5, importance)),
            metadata=metadata or {},
        )

        # Append to file
        with self.memories_file.open("a") as f:
            f.write(json.dumps(entry.__dict__) + "\n")

        # Invalidate index
        self._dirty = True
        return entry.id

    def search(
        self,
        query: str,
        k: int | None = None,
        tags: list[str] | None = None,
        min_importance: int = 1,
    ) -> list[MemoryEntry]:
        """Search memories by keyword relevance."""
        entries = self._all()
        if not entries:
            return []

        k = k or self.max_results
        scored = []
        for doc in entries.values():
            if doc.importance < min_importance:
                continue
            if tags and not any(t in doc.tags for t in tags):
                continue
            score = self._score(query, doc)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:k]]

    def get(self, memory_id: str) -> MemoryEntry | None:
        entries = self._all()
        return entries.get(memory_id)

    def delete(self, memory_id: str) -> bool:
        entries = self._all()
        if memory_id not in entries:
            return False
        del entries[memory_id]
        self._save_all(list(entries.values()))
        self._dirty = True
        return True

    def tag(self, memory_id: str, add: list[str] | None = None, remove: list[str] | None = None):
        entries = self._all()
        if memory_id not in entries:
            return False
        doc = entries[memory_id]
        if add:
            doc.tags = list(set(doc.tags) | set(add))
        if remove:
            doc.tags = [t for t in doc.tags if t not in remove]
        self._save_all(list(entries.values()))
        self._dirty = True
        return True

    def list(self, n: int = 20) -> list[MemoryEntry]:
        entries = list(self._all().values())
        return list(reversed(entries[-n:]))

    def clear(self):
        self.memories_file.write_text("")
        self._dirty = True

    def export(self, format: str = "json") -> str:
        entries = list(self._all().values())
        if format == "json":
            return json.dumps([d.__dict__ for d in entries], indent=2)
        elif format == "md":
            lines = ["# Memories\n"]
            for d in entries:
                tags = " ".join(f"#{t}" for t in d.tags)
                lines.append(f"- **{d.id}** ({d.timestamp}) [{d.importance}/5] {tags}")
            return "\n".join(lines)
        else:
            return f"Unknown format: {format}"
        return ""

    def __len__(self) -> int:
        return len(self._all())