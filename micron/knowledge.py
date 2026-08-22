"""KnowledgeIndex — deep module owning knowledge discovery + TF-IDF.

Single owner for: glob, YAML frontmatter/title stripping, whitespace collapse,
TFIDFIndex lifecycle with mtime snapshot, ranking, and budget packing.
Adapters: PromptBuilder._load_knowledge and search_knowledge tool.
Seam: KnowledgeIndex(knowledge_dir: Path|None) — local-substitutable via tmp_path.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from micron.search import TFIDFIndex


def budget_join(
    chunks: list[str],
    *,
    budget: int = 8000,
    label: str = "items",
    sep: str = "\n\n---\n\n",
) -> str:
    if not chunks:
        return ""
    parts: list[str] = []
    total = 0
    for c in chunks:
        if not c:
            continue
        if total + len(c) > budget:
            remaining = len(chunks) - len(parts)
            if remaining > 0:
                parts.append(f"*({remaining} more {label} not shown — prompt budget limit)*")
            break
        parts.append(c)
        total += len(c)
    return sep.join(parts)


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    slug: str
    score: float
    snippet: str
    content: str
    raw: str


def _parse_text(raw: str) -> str:
    txt = raw.strip()
    if txt.startswith("---"):
        parts = txt.split("---", 2)
        if len(parts) >= 3:
            txt = parts[2]
    txt = re.sub(r"^# .*$", "", txt, flags=re.MULTILINE)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _resolve_knowledge_dir(knowledge_dir: Path | str | None) -> Path:
    if knowledge_dir is not None:
        return Path(knowledge_dir).resolve()
    env = os.getenv("MICRON_CONTEXT_DIR")
    if env:
        return (Path(env) / "knowledge").resolve()
    workdir = os.getenv("MICRON_WORKDIR")
    if workdir:
        return (Path(workdir) / "context" / "knowledge").resolve()
    try:
        from micron.config import Config

        ctx = Config().get("context_dir", "context")
        p = Path(ctx)
        if not p.is_absolute():
            p = Path(__file__).parent.parent / p
        return (p / "knowledge").resolve()
    except Exception:
        return (Path.cwd() / "context" / "knowledge").resolve()


class KnowledgeIndex:
    """Deep module — discovery + parsing + TF-IDF + budget behind one seam."""

    def __init__(self, knowledge_dir: Path | str | None = None):
        self._dir = _resolve_knowledge_dir(knowledge_dir)
        self._index = TFIDFIndex()
        self._docs_parsed: dict[str, str] = {}  # slug -> parsed content (>5 chars)
        self._docs_raw: dict[str, str] = {}  # slug -> raw stripped original
        self._full_raw: dict[str, str] = {}  # slug -> full raw file text for prompt packing (not collapsed snippet)
        self._snapshot: dict[Path, tuple[float, int]] = {}
        self._dirty = True

    def _is_stale(self) -> bool:
        if self._dirty:
            return True
        if not self._dir.exists():
            return bool(self._docs_parsed)
        try:
            current = {p: (p.stat().st_mtime, p.stat().st_size) for p in self._dir.glob("*.md")}
        except Exception:
            return True
        return current != self._snapshot

    def _ensure_fresh(self) -> None:
        if not self._is_stale():
            return
        self.reload()

    def reload(self) -> None:
        self._index.clear()
        self._docs_parsed.clear()
        self._docs_raw.clear()
        self._full_raw.clear()
        if not self._dir.exists():
            self._snapshot = {}
            self._dirty = False
            return
        files = sorted(self._dir.glob("*.md"))
        snapshot: dict[Path, tuple[float, int]] = {}
        for f in files:
            try:
                snapshot[f] = (f.stat().st_mtime, f.stat().st_size)
            except Exception:
                continue
            try:
                raw_full = f.read_text(errors="replace").strip()
                if not raw_full:
                    continue
                # Keep full raw for prompt packing (like old PromptBuilder which joined raw content)
                # But also need parsed for index
                parsed = _parse_text(raw_full)
                if parsed and len(parsed) > 5:
                    slug = f.stem
                    # parsed for TFIDF
                    self._docs_parsed[slug] = parsed
                    # raw collapsed 300 snippet source? Use parsed collapsed for snippet
                    # Keep parsed as raw for hit content, full raw separately
                    self._docs_raw[slug] = parsed
                    self._full_raw[slug] = raw_full
                    self._index.add(slug, parsed)
                elif not parsed:
                    # empty after parse — skip
                    continue
            except Exception:
                continue
        self._snapshot = snapshot
        self._dirty = False

    # 80% path for PromptBuilder
    def prompt_context(self, query: str, *, k: int = 5, budget: int = 8000) -> str:
        if not self._dir.exists():
            return "(no knowledge files loaded)"
        self._ensure_fresh()
        if not self._docs_parsed:
            return "(no knowledge files loaded)"
        if query and query.strip():
            results = self._index.search(query, k=1000)  # rank all, then budget pack
            scored_slugs = [(slug, score) for slug, score in results if score > 0]
            if not scored_slugs:
                return "(no relevant knowledge)"
            # Map to full raw content for prompt (preserve markdown as stored)
            files_with_content: list[tuple[str, str]] = []
            for slug, _ in scored_slugs:
                full = self._full_raw.get(slug, self._docs_raw.get(slug, ""))
                if full:
                    files_with_content.append((slug, full))
        else:
            # No query: return all files with content (like old else branch)
            files_with_content = [(slug, self._full_raw.get(slug, self._docs_raw[slug])) for slug in sorted(self._full_raw.keys())]
            if not files_with_content:
                return "(no relevant knowledge)"
        contents = [c for _, c in files_with_content if c]
        if not contents:
            return "(no knowledge files loaded)"
        packed = budget_join(contents, budget=budget, label="knowledge files")
        return packed if packed else "(no knowledge files loaded)"

    def search(self, query: str, *, k: int = 5) -> list[KnowledgeHit]:
        if not self._dir.exists():
            return []
        self._ensure_fresh()
        if not self._docs_parsed:
            return []
        if not query or not query.strip():
            return []
        results = self._index.search(query, k=k)
        hits: list[KnowledgeHit] = []
        for slug, score in results:
            parsed = self._docs_raw.get(slug, "")
            full_raw = self._full_raw.get(slug, parsed)
            snippet = parsed[:300].replace("\n", " ").strip()
            hits.append(KnowledgeHit(slug=slug, score=score, snippet=snippet, content=parsed, raw=full_raw))
        return hits

    def get(self, slug: str) -> str | None:
        self._ensure_fresh()
        return self._docs_raw.get(slug)

    def docs(self) -> dict[str, str]:
        self._ensure_fresh()
        return dict(self._docs_raw)

    @property
    def size(self) -> int:
        self._ensure_fresh()
        return len(self._docs_raw)


_knowledge_singleton: KnowledgeIndex | None = None
_knowledge_snap: str | None = None


def get_knowledge_index() -> KnowledgeIndex:
    global _knowledge_singleton, _knowledge_snap
    snap = os.getenv("MICRON_CONTEXT_DIR") or os.getenv("MICRON_WORKDIR") or ""
    if _knowledge_singleton is None or _knowledge_snap != snap:
        _knowledge_singleton = KnowledgeIndex()
        _knowledge_snap = snap
    return _knowledge_singleton
