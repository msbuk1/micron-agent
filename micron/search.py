"""Shared TF-IDF search index — pure Python, zero deps.

Used by memory.py and knowledge search for consistent scoring.
"""
import math
import re
from collections import Counter
from typing import List, Tuple, Optional


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
        self._tokens: dict[str, List[str]] = {}
        self._tf: dict[str, Counter] = {}
        self._idf: dict[str, float] = {}
        self._dirty = True
        self._n_docs = 0
    
    def add(self, doc_id: str, text: str):
        """Add or update a document."""
        self._docs[doc_id] = text
        self._tokens[doc_id] = tokenize(text)
        self._dirty = True
    
    def remove(self, doc_id: str):
        """Remove a document."""
        if doc_id in self._docs:
            del self._docs[doc_id]
            if doc_id in self._tokens:
                del self._tokens[doc_id]
            if doc_id in self._tf:
                del self._tf[doc_id]
            self._dirty = True
    
    def clear(self):
        """Remove all documents."""
        self._docs.clear()
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
