"""Shared TF-IDF search index — pure Python, zero deps.

Used by memory.py and knowledge search for consistent scoring.
"""
import math
import re
from collections import Counter
from typing import Any, List, Tuple, Optional


def tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase words."""
    return re.findall(r"\b\w+\b", text.lower())


class TFIDFIndex:
    """TF-IDF search index for in-memory document collections.
    
    Usage:
        index = TFIDFIndex()
        index.add("doc1", "Some document text")
        index.add("doc2", "Another document")
        
        results = index.search("search query", k=5)
        # Returns: [(doc_id, score), ...]
    """
    
    def __init__(self):
        self._docs: dict[str, str] = {}
        self._objects: dict[str, Any] = {}  # optional full doc objects by id
        self._tokens: dict[str, List[str]] = {}
        self._tf: dict[str, Counter] = {}
        self._idf: dict[str, float] = {}
        self._dirty = True
        self._n_docs = 0

    def add(self, doc_id: str, text: str, doc: Any = None):
        """Add or update a document.

        ``doc`` is an optional arbitrary object stored alongside the text so
        the index can act as a sole store for a richer document model. When
        omitted, ``get_doc``/``docs`` return the text string.
        """
        self._docs[doc_id] = text
        if doc is not None:
            self._objects[doc_id] = doc
        self._tokens[doc_id] = tokenize(text)
        self._dirty = True

    def get_doc(self, doc_id: str) -> Any:
        """Return the full object stored for a doc id (falls back to text)."""
        return self._objects.get(doc_id, self._docs.get(doc_id))

    def docs(self) -> dict[str, Any]:
        """Return all documents as {id: object-or-text}."""
        return {i: self._objects.get(i, t) for i, t in self._docs.items()}

    def remove(self, doc_id: str):
        """Remove a document."""
        if doc_id in self._docs:
            del self._docs[doc_id]
            self._objects.pop(doc_id, None)
            if doc_id in self._tokens:
                del self._tokens[doc_id]
            if doc_id in self._tf:
                del self._tf[doc_id]
            self._dirty = True

    def clear(self):
        """Remove all documents."""
        self._docs.clear()
        self._objects.clear()
        self._tokens.clear()
        self._tf.clear()
        self._idf.clear()
        self._dirty = True
    
    def _rebuild(self):
        """Rebuild TF-IDF index."""
        self._tf.clear()
        self._idf.clear()
        self._n_docs = len(self._docs)
        
        if self._n_docs == 0:
            self._dirty = False
            return
        
        # Build TF for each document
        vocab = set()
        for doc_id, tokens in self._tokens.items():
            self._tf[doc_id] = Counter(tokens)
            vocab.update(tokens)
        
        # Calculate IDF: log(N / df) + 1.0
        for term in vocab:
            df = sum(1 for tf in self._tf.values() if term in tf)
            self._idf[term] = (math.log(self._n_docs / df) + 1.0) if df > 0 else 0.0
        
        self._dirty = False
    
    def score(self, query: str, doc_id: str) -> float:
        """Score a document against a query."""
        if self._dirty:
            self._rebuild()
        
        if doc_id not in self._tf:
            return 0.0
        
        query_tokens = tokenize(query)
        if not query_tokens:
            return 0.0
        
        tf = self._tf[doc_id]
        score = 0.0
        for token in query_tokens:
            if token in self._idf:
                score += tf.get(token, 0) * self._idf[token]
        
        return score
    
    def search(self, query: str, k: int = 5) -> List[Tuple[str, float]]:
        """Search documents by relevance.
        
        Args:
            query: Search query
            k: Number of results to return
            
        Returns:
            List of (doc_id, score) tuples, sorted by score descending
        """
        if self._dirty:
            self._rebuild()
        
        if not self._docs or not query.strip():
            return []
        
        results = []
        for doc_id in self._docs:
            score = self.score(query, doc_id)
            if score > 0:
                results.append((doc_id, score))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]
    
    def get_idf(self, term: str) -> float:
        """Get IDF score for a term."""
        if self._dirty:
            self._rebuild()
        return self._idf.get(term, 0.0)
    
    @property
    def size(self) -> int:
        """Number of documents in the index."""
        return len(self._docs)
