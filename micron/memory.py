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

        # TF-IDF index
        self._docs: list[MemoryEntry] = []
        self._vocab: set[str] = set()
        self._tf: list[Counter] = []
        self._idf: dict[str, float] = {}
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
        self._docs = self._load()
        self._tf = []
        self._vocab = set()

        for doc in self._docs:
            tokens = self._tokenize(doc.text)
            self._tf.append(Counter(tokens))
            self._vocab.update(tokens)

        n_docs = len(self._docs)
        self._idf = {}
        for term in self._vocab:
            df = sum(1 for tf in self._tf if term in tf)
            self._idf[term] = (math.log(n_docs / df) + 1.0) if df > 0 else 0.0

        self._dirty = False

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"\b\w+\b", text.lower())

    def _score(self, query: str, doc_idx: int) -> float:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return 0.0

        tf = self._tf[doc_idx]
        score = 0.0
        for token in query_tokens:
            if token in self._idf:
                score += tf.get(token, 0) * self._idf[token]

        # Time decay
        doc = self._docs[doc_idx]
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
        if self._dirty:
            self._rebuild_index()

        if not self._docs:
            return []

        k = k or self.max_results
        scored = []
        for i, doc in enumerate(self._docs):
            if doc.importance < min_importance:
                continue
            if tags and not any(t in doc.tags for t in tags):
                continue
            score = self._score(query, i)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:k]]

    def get(self, memory_id: str) -> MemoryEntry | None:
        if self._dirty:
            self._rebuild_index()
        for doc in self._docs:
            if doc.id == memory_id:
                return doc
        return None

    def delete(self, memory_id: str) -> bool:
        if self._dirty:
            self._rebuild_index()
        before = len(self._docs)
        self._docs = [d for d in self._docs if d.id != memory_id]
        if len(self._docs) < before:
            self._save_all(self._docs)
            self._dirty = True
            return True
        return False

    def tag(self, memory_id: str, add: list[str] | None = None, remove: list[str] | None = None):
        if self._dirty:
            self._rebuild_index()
        for doc in self._docs:
            if doc.id == memory_id:
                if add:
                    doc.tags = list(set(doc.tags) | set(add))
                if remove:
                    doc.tags = [t for t in doc.tags if t not in remove]
                self._save_all(self._docs)
                self._dirty = True
                return True
        return False

    def list(self, n: int = 20) -> list[MemoryEntry]:
        if self._dirty:
            self._rebuild_index()
        return list(reversed(self._docs[-n:]))

    def clear(self):
        self.memories_file.write_text("")
        self._dirty = True

    def export(self, format: str = "json") -> str:
        if self._dirty:
            self._rebuild_index()
        if format == "json":
            return json.dumps([d.__dict__ for d in self._docs], indent=2)
        elif format == "md":
            lines = ["# Memories\n"]
            for d in self._docs:
                tags = " ".join(f"#{t}" for t in d.tags)
                lines.append(f"- **{d.id}** ({d.timestamp}) [{d.importance}/5] {tags}")
                lines.append(f"  {d.text}")
                lines.append("")
            return "\n".join(lines)
        return ""

    def __len__(self) -> int:
        if self._dirty:
            self._rebuild_index()
        return len(self._docs)