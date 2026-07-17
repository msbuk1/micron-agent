"""Tests for the shared TFIDFIndex search module."""
import pytest
from micron.search import TFIDFIndex, tokenize


class TestTokenize:
    """Tests for the tokenize function."""
    
    def test_basic_tokenization(self):
        """Test basic word tokenization."""
        result = tokenize("Hello World")
        assert result == ["hello", "world"]
    
    def test_punctuation_removed(self):
        """Test that punctuation is removed."""
        result = tokenize("hello, world! How are you?")
        assert result == ["hello", "world", "how", "are", "you"]
    
    def test_empty_string(self):
        """Test empty string returns empty list."""
        result = tokenize("")
        assert result == []
    
    def test_numbers_included(self):
        """Test that numbers are included."""
        result = tokenize("test 123 numbers")
        assert result == ["test", "123", "numbers"]


class TestTFIDFIndex:
    """Tests for the TFIDFIndex class."""
    
    def test_add_and_search(self):
        """Test adding documents and searching."""
        index = TFIDFIndex()
        index.add("doc1", "python programming language")
        index.add("doc2", "java programming language")
        index.add("doc3", "cooking recipes")
        
        results = index.search("python")
        assert len(results) == 1
        assert results[0][0] == "doc1"
    
    def test_multiple_results(self):
        """Test returning multiple results."""
        index = TFIDFIndex()
        index.add("doc1", "python programming")
        index.add("doc2", "python coding")
        index.add("doc3", "java programming")
        
        results = index.search("python", k=2)
        assert len(results) == 2
        # Both python docs should be returned
        doc_ids = [r[0] for r in results]
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids
    
    def test_relevance_scoring(self):
        """Test that more relevant docs score higher."""
        index = TFIDFIndex()
        index.add("doc1", "python python python")  # 3x python
        index.add("doc2", "python language")  # 1x python
        
        results = index.search("python")
        assert results[0][0] == "doc1"  # More relevant
        assert results[0][1] > results[1][1]  # Higher score
    
    def test_remove_document(self):
        """Test removing a document."""
        index = TFIDFIndex()
        index.add("doc1", "python programming")
        index.add("doc2", "java programming")
        
        index.remove("doc1")
        results = index.search("python")
        assert len(results) == 0
        
        results = index.search("java")
        assert len(results) == 1
        assert results[0][0] == "doc2"
    
    def test_clear_index(self):
        """Test clearing all documents."""
        index = TFIDFIndex()
        index.add("doc1", "python programming")
        index.add("doc2", "java programming")
        
        index.clear()
        assert index.size == 0
        results = index.search("python")
        assert len(results) == 0
    
    def test_empty_query(self):
        """Test empty query returns empty results."""
        index = TFIDFIndex()
        index.add("doc1", "python programming")
        
        results = index.search("")
        assert len(results) == 0
    
    def test_no_matches(self):
        """Test query with no matches."""
        index = TFIDFIndex()
        index.add("doc1", "python programming")
        
        results = index.search("cooking")
        assert len(results) == 0
    
    def test_size_property(self):
        """Test size property."""
        index = TFIDFIndex()
        assert index.size == 0
        
        index.add("doc1", "python")
        assert index.size == 1
        
        index.add("doc2", "java")
        assert index.size == 2
        
        index.remove("doc1")
        assert index.size == 1
    
    def test_get_idf(self):
        """Test getting IDF score for a term."""
        index = TFIDFIndex()
        index.add("doc1", "python programming")
        index.add("doc2", "java programming")
        
        # "programming" appears in 2 docs, should have lower IDF
        # "python" appears in 1 doc, should have higher IDF
        idf_python = index.get_idf("python")
        idf_programming = index.get_idf("programming")
        
        assert idf_python > idf_programming
    
    def test_update_document(self):
        """Test updating a document (same ID)."""
        index = TFIDFIndex()
        index.add("doc1", "python programming")
        
        # Update with new content
        index.add("doc1", "java programming")
        
        # Should find java, not python
        results = index.search("java")
        assert len(results) == 1
        assert results[0][0] == "doc1"
        
        results = index.search("python")
        assert len(results) == 0
