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

import json

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
        self._index_file = self._dir / ".knowledge_index.json"
        self._index_md = self._dir / ".knowledge_index.md"

    def _glob_files(self) -> list[Path]:
        files: list[Path] = []
        for ext in ("*.md", "*.txt", "*.pdf"):
            for f in self._dir.glob(ext):
                if f.name.startswith("."):
                    continue
                if f.name == "index.md":
                    continue
                files.append(f)
        return sorted(files)

    def _read_raw(self, f: Path) -> str:
        if f.suffix.lower() == ".pdf":
            try:
                import pymupdf  # type: ignore

                doc = pymupdf.open(str(f))
                parts: list[str] = []
                for page in doc:
                    parts.append(page.get_text())
                doc.close()
                return "\n".join(parts).strip()
            except Exception:
                # Fallback to read as text (will be binary)
                try:
                    return f.read_text(errors="replace").strip()
                except Exception:
                    return ""
        return f.read_text(errors="replace").strip()

    def _is_stale(self) -> bool:
        if self._dirty:
            return True
        if not self._dir.exists():
            return bool(self._docs_parsed)
        try:
            current = {p: (p.stat().st_mtime, p.stat().st_size) for p in self._glob_files()}
        except Exception:
            return True
        return current != self._snapshot

    def _ensure_fresh(self) -> None:
        if not self._is_stale():
            return
        self.reload()

    def _load_persisted(self, current_snapshot: dict[Path, tuple[float, int]]) -> bool:
        try:
            if not self._index_file.exists():
                return False
            data = json.loads(self._index_file.read_text())
            saved_snap = {Path(k): tuple(v) for k, v in data.get("snapshot", {}).items()}
            if saved_snap != current_snapshot:
                return False
            docs = data.get("docs", {})
            if not docs:
                return False
            self._index.clear()
            self._docs_parsed.clear()
            self._docs_raw.clear()
            self._full_raw.clear()
            for slug, parsed in docs.items():
                self._docs_parsed[slug] = parsed
                self._docs_raw[slug] = parsed
                # full_raw not persisted to keep index small; search uses parsed
                self._index.add(slug, parsed)
            self._snapshot = current_snapshot
            self._dirty = False
            return True
        except Exception:
            return False

    def _save_persisted(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            data = {
                "snapshot": {str(k): list(v) for k, v in self._snapshot.items()},
                "docs": self._docs_parsed,
            }
            self._index_file.write_text(json.dumps(data))
        except Exception:
            pass

    def _generate_index_md(self) -> None:
        try:
            if not self._docs_parsed:
                if self._index_md.exists():
                    self._index_md.unlink()
                return
            lines = ["# Knowledge Index", "", f"Updated: {__import__('datetime').datetime.now().isoformat()}", f"Docs: {len(self._docs_parsed)}", "", "| slug | chars | snippet |", "| --- | --- | --- |"]
            for slug in sorted(self._docs_parsed.keys()):
                parsed = self._docs_parsed[slug]
                snippet = parsed[:200].replace("|", "/").replace("\n", " ").strip()
                lines.append(f"| {slug} | {len(parsed)} | {snippet}… |")
            lines.append("")
            lines.append("_Full docs via search_knowledge tool_")
            self._index_md.write_text("\n".join(lines))
        except Exception:
            pass

    def index_context(self, budget: int = 8000) -> str:
        """Tiny index.md for system prompt — not full docs. Fast-path avoids TFIDF rebuild."""
        # Fast path: if .knowledge_index.md exists and is newer than all source files, read it directly
        try:
            if self._index_md.exists():
                md_mtime = self._index_md.stat().st_mtime
                files = self._glob_files()
                if files and all(f.stat().st_mtime < md_mtime for f in files):
                    txt = self._index_md.read_text().strip()
                    if txt:
                        if len(txt) > budget:
                            txt = txt[:budget] + "\n… [truncated]"
                        return txt
                elif not files:
                    return "(no knowledge files loaded)"
        except Exception:
            pass
        self._ensure_fresh()
        if not self._docs_parsed:
            return "(no knowledge files loaded)"
        try:
            if self._index_md.exists():
                txt = self._index_md.read_text().strip()
                if txt:
                    if len(txt) > budget:
                        txt = txt[:budget] + "\n… [truncated]"
                    return txt
        except Exception:
            pass
        lines = [f"- {slug} ({len(p)} chars)" for slug, p in sorted(self._docs_parsed.items())]
        txt = "\n".join(lines)
        if len(txt) > budget:
            txt = txt[:budget] + "\n… [truncated]"
        return txt or "(no knowledge files loaded)"

    def reload(self) -> None:
        if not self._dir.exists():
            self._index.clear()
            self._docs_parsed.clear()
            self._docs_raw.clear()
            self._full_raw.clear()
            self._snapshot = {}
            self._dirty = False
            return
        files = self._glob_files()
        current_snapshot: dict[Path, tuple[float, int]] = {}
        for f in files:
            try:
                current_snapshot[f] = (f.stat().st_mtime, f.stat().st_size)
            except Exception:
                continue
        # Fast path: load persisted if snapshot matches
        if not self._dirty and self._load_persisted(current_snapshot):
            return
        # Also try persisted even when dirty (cold start)
        if self._dirty and self._load_persisted(current_snapshot):
            return
        # Rebuild from scratch (extract PDFs)
        self._index.clear()
        self._docs_parsed.clear()
        self._docs_raw.clear()
        self._full_raw.clear()
        for f in files:
            try:
                raw_full = self._read_raw(f)
                if not raw_full:
                    continue
                parsed = _parse_text(raw_full)
                if parsed and len(parsed) > 5:
                    slug = f.stem
                    self._docs_parsed[slug] = parsed
                    self._docs_raw[slug] = parsed
                    self._full_raw[slug] = raw_full
                    self._index.add(slug, parsed)
            except Exception:
                continue
        self._snapshot = current_snapshot
        self._dirty = False
        self._save_persisted()
        self._generate_index_md()

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
