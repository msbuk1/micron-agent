# ADR 0004 — KnowledgeIndex deep module

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** codebase review (design-it-twice P2)
- **Origin:** P2 candidate — `PromptBuilder._load_knowledge:137` (word-overlap) + `search_knowledge:726` (per-call `TFIDFIndex`) duplicate 90 LOC

## Context

Two call sites owned the same `context/knowledge/*.md` concern with different ranking:

- `PromptBuilder._load_knowledge` did `glob("*.md")` + `sum(1 for w in query if w in content)` + `8000`-char budget join.
- `search_knowledge` did `glob("*.md")` + YAML `---` strip + `re.sub(^#…)` + `re.sub(\s+)` + `len>5` guard + `TFIDFIndex` build per call + `[slug] (score: X) snippet…`.

Fixing YAML handling or budget required two patches; `write_knowledge` needed manual `reload` to be seen. `Memory` already showed `TFIDFIndex` as sole store with `mtime` dirty rebuild.

## Decision

`micron/knowledge.py:1`:

```python
@dataclass(frozen=True) class KnowledgeHit: slug, score, snippet, content, raw
class KnowledgeIndex:
    def __init__(self, knowledge_dir: Path|str|None=None): ...  # None→MICRON_CONTEXT_DIR→workdir/knowledge
    def prompt_context(self, query: str, *, k=5, budget=8000) -> str: ...  # budgeted block or sentinel
    def search(self, query: str, *, k=5) -> list[KnowledgeHit]: ...        # structured, snippet=[:300]
    def get(slug)->str|None; def docs()->dict; def reload()->None; @property def size->int
def get_knowledge_index()->KnowledgeIndex: ...  # singleton env-snap like _ws
```

Internal: sorted `glob("*.md")`, `_parse_text` (YAML frontmatter `---` split + title `^# ` removal + whitespace collapse), owned `TFIDFIndex` + `snapshot: dict[Path,(mtime,size)]` for `_ensure_fresh`/`reload`, ranking via `index.search`, sentinels `(no knowledge files loaded)`/`(no relevant knowledge)`/`(knowledge directory not found)`/`(no knowledge documents)`/`(no search query)` preserved. `PromptBuilder` takes `knowledge:KnowledgeIndex|None` (default `context_dir/knowledge`, injectable `tmp_path`); `_load_knowledge` → `knowledge_index.prompt_context`. `search_knowledge` → `KnowledgeIndex` singleton + `len>5` + formatting. No external port beyond `Path`.

Rejected: (B) 6-policy composition (`Discovery`/`Parser`/`Chunker`/`Ranking`/`Snippet`/`Render` with `HeadingChunk`/`HybridRanker`) — one chunking adapter not worth explosion; (A) 2-verb `for_prompt/search->str` — hides structured `Hit` needed for tool tests. Chose ergonomic C: prompt gets `str`, tool gets testable `list[Hit]`.

## Consequences

### Positive

- **Locality** — YAML/title/budget in one file; fix shares `KnowledgeIndex` to both adapters.
- **Leverage** — prompt now gets TF-IDF for free; index reused via dirty snapshot vs per-call rebuild.
- **Testability** — `KnowledgeIndex(tmp_path).prompt_context/search` via `tmp_path`, no env.

### Negative

- `prompt_context` returns full raw markdown including frontmatter (preserves old `prompt.py` behavior) — differs from `search` snippet collapse; not unified.
- `reload` is explicit; no `inotify` watch — hot loop does `stat` per `prompt_context`/`search` call (ok for <1k files).
- `WorkspaceFS` not reused for reads — knowledge read-only, avoids coupling to workdir containment.
