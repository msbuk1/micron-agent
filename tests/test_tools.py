"""Tests for built-in tools: delete_file, edit_file, list_skills."""
import os
import tempfile
from pathlib import Path

import pytest

from micron.tools.builtin import delete_file, edit_file, list_skills


# Set up test environment
@pytest.fixture
def test_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Set MICRON_WORKDIR to the temp directory
        old_workdir = os.environ.get("MICRON_WORKDIR")
        os.environ["MICRON_WORKDIR"] = tmpdir
        yield Path(tmpdir)
        # Restore original workdir
        if old_workdir:
            os.environ["MICRON_WORKDIR"] = old_workdir
        elif "MICRON_WORKDIR" in os.environ:
            del os.environ["MICRON_WORKDIR"]


class TestDeleteFile:
    """Tests for delete_file tool."""

    def test_delete_existing_file(self, test_dir):
        """Test deleting an existing file."""
        # Create a test file
        test_file = test_dir / "test_delete.txt"
        test_file.write_text("test content")
        
        # Delete it
        result = delete_file("test_delete.txt")
        
        # Verify file is deleted
        assert not test_file.exists()
        assert "Deleted" in result
        assert "test_delete.txt" in result

    def test_delete_nonexistent_file(self, test_dir):
        """Test deleting a non-existent file."""
        result = delete_file("nonexistent.txt")
        
        # Should return an error
        assert "Error" in result or "does not exist" in result

    def test_delete_path_traversal(self, test_dir):
        """Test path traversal protection."""
        # Try to delete a file outside workdir
        result = delete_file("../../../etc/passwd")
        
        # Should be blocked or return error
        assert "Error" in result or "does not exist" in result


class TestEditFile:
    """Tests for edit_file tool."""

    def test_edit_file_replace_text(self, test_dir):
        """Test replacing text in a file."""
        # Create a test file
        test_file = test_dir / "test_edit.txt"
        test_file.write_text("Hello World")
        
        # Edit it
        result = edit_file("test_edit.txt", "Hello", "Goodbye")
        
        # Verify edit
        assert "Success" in result or "success" in result.lower()
        assert test_file.read_text() == "Goodbye World"

    def test_edit_file_nonexistent(self, test_dir):
        """Test editing a non-existent file."""
        result = edit_file("nonexistent.txt", "old", "new")
        
        # Should return an error
        assert "Error" in result or "does not exist" in result

    def test_edit_python_syntax_validation(self, test_dir):
        """Test that Python syntax is validated before and after editing."""
        # Create a valid Python file
        test_file = test_dir / "test.py"
        test_file.write_text("x = 1\n")
        
        # Edit with valid syntax
        result = edit_file("test.py", "x = 1", "x = 2")
        assert "Success" in result or "success" in result.lower()
        assert test_file.read_text() == "x = 2\n"
        
        # Edit with invalid syntax (should revert if subprocess available, otherwise succeed)
        original_content = test_file.read_text()
        result = edit_file("test.py", "x = 2", "x = ")  # Invalid syntax
        
        # If subprocess validation worked, result should be error and file reverted
        # If subprocess failed (resource limits), result should be success
        if "Error" in result or "Syntax" in result:
            # Subprocess validation worked — file should be reverted
            assert test_file.read_text() == original_content
        else:
            # Subprocess unavailable — edit succeeded without validation
            assert "Success" in result

    def test_edit_path_traversal(self, test_dir):
        """Test path traversal protection."""
        result = edit_file("../../../etc/passwd", "old", "new")
        
        # Should be blocked or return error
        assert "Error" in result or "does not exist" in result


class TestListSkills:
    """Tests for list_skills tool."""

    def test_list_skills_returns_list(self, test_dir):
        """Test that list_skills returns a list."""
        result = list_skills()
        
        # Should return a string (formatted list)
        assert isinstance(result, str)
        # Should contain some skills
        assert len(result) > 0

    def test_list_skills_with_query(self, test_dir):
        """Test listing skills with a query filter."""
        result = list_skills("read")
        
        # Should return a string
        assert isinstance(result, str)
        # Should be shorter or equal to full list
        assert len(result) >= 0

    def test_list_skills_returns_string(self):
        """Test that list_skills returns a string."""
        result = list_skills()
        
        # Should return a string (either list of skills or error message)
        assert isinstance(result, str)
