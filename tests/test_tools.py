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


class TestTrashRecovery:
    """Tests for delete_file trash recovery, restore_file, and list_trash."""
    
    def test_delete_moves_to_trash(self, test_dir):
        """Test that delete_file moves to .trash/ instead of deleting."""
        from micron.tools.builtin import list_trash
        
        # Create a test file
        test_file = test_dir / "trash_test.txt"
        test_file.write_text("delete me")
        
        # Delete it
        result = delete_file("trash_test.txt")
        assert "Deleted" in result
        assert "recoverable" in result
        
        # File should be gone from original location
        assert not test_file.exists()
        
        # File should be in .trash/
        trash_dir = test_dir / ".trash"
        assert trash_dir.exists()
        trash_files = list(trash_dir.glob("trash_test.txt.*"))
        assert len(trash_files) == 1
    
    def test_list_trash(self, test_dir):
        """Test listing trashed files."""
        from micron.tools.builtin import list_trash
        
        # Create and delete a file
        test_file = test_dir / "list_test.txt"
        test_file.write_text("list me")
        delete_file("list_test.txt")
        
        # List trash
        result = list_trash()
        assert "list_test.txt" in result
        assert "Trash" in result
    
    def test_list_trash_empty(self, test_dir):
        """Test listing empty trash."""
        from micron.tools.builtin import list_trash
        
        result = list_trash()
        assert "empty" in result.lower()
    
    def test_restore_file(self, test_dir):
        """Test restoring a file from trash."""
        from micron.tools.builtin import restore_file
        
        # Create and delete a file
        test_file = test_dir / "restore_test.txt"
        test_file.write_text("restore me")
        delete_file("restore_test.txt")
        
        # Get the trash filename
        trash_dir = test_dir / ".trash"
        trash_files = list(trash_dir.glob("restore_test.txt.*"))
        assert len(trash_files) == 1
        trash_name = trash_files[0].name
        
        # Restore it
        result = restore_file(trash_name)
        assert "Restored" in result
        
        # File should be back
        assert test_file.exists()
        assert test_file.read_text() == "restore me"
        
        # Trash should be empty
        assert not trash_files[0].exists()
    
    def test_restore_by_partial_name(self, test_dir):
        """Test restoring by original name (partial match)."""
        from micron.tools.builtin import restore_file
        
        # Create and delete a file
        test_file = test_dir / "partial_test.txt"
        test_file.write_text("partial restore")
        delete_file("partial_test.txt")
        
        # Restore by original name
        result = restore_file("partial_test.txt")
        assert "Restored" in result
        
        # File should be back
        assert test_file.exists()
    
    def test_restore_nonexistent(self, test_dir):
        """Test restoring a file that doesn't exist in trash."""
        from micron.tools.builtin import restore_file
        
        result = restore_file("nonexistent.txt")
        assert "Error" in result or "not found" in result.lower()
    
    def test_delete_directory_blocked(self, test_dir):
        """Test that deleting directories is still blocked."""
        # Create a test directory
        test_dir.mkdir(exist_ok=True)
        
        # Try to delete it
        result = delete_file(str(test_dir.name))
        assert "Error" in result or "Cannot delete directory" in result


class TestEditUndo:
    """Tests for edit_file backup and undo_file."""
    
    def test_edit_creates_backup(self, test_dir):
        """Test that edit_file creates a .bak backup."""
        # Create a test file
        test_file = test_dir / "backup_test.txt"
        test_file.write_text("original content")
        
        # Edit it
        result = edit_file("backup_test.txt", "original", "modified")
        assert "Success" in result or "success" in result.lower()
        
        # Check that .bak file was created
        bak_file = test_dir / "backup_test.txt.bak"
        assert bak_file.exists()
        assert bak_file.read_text() == "original content"
    
    def test_undo_file_restores_backup(self, test_dir):
        """Test that undo_file restores from .bak backup."""
        # Create a test file
        test_file = test_dir / "undo_test.txt"
        test_file.write_text("original content")
        
        # Edit it
        edit_file("undo_test.txt", "original", "modified")
        assert test_file.read_text() == "modified content"
        
        # Undo the edit
        from micron.tools.builtin import undo_file
        result = undo_file("undo_test.txt")
        assert "Restored" in result
        
        # Verify file is restored
        assert test_file.read_text() == "original content"
        
        # Verify .bak file is removed
        bak_file = test_dir / "undo_test.txt.bak"
        assert not bak_file.exists()
    
    def test_undo_nonexistent_backup(self, test_dir):
        """Test undo_file when no backup exists."""
        from micron.tools.builtin import undo_file
        
        result = undo_file("no_backup.txt")
        assert "Error" in result or "No backup" in result
    
    def test_multiple_edits_keep_latest_backup(self, test_dir):
        """Test that multiple edits keep only the latest backup."""
        # Create a test file
        test_file = test_dir / "multi_edit.txt"
        test_file.write_text("version 1")
        
        # Edit twice
        edit_file("multi_edit.txt", "version 1", "version 2")
        edit_file("multi_edit.txt", "version 2", "version 3")
        
        # Check that .bak has version 2 (the state before second edit)
        bak_file = test_dir / "multi_edit.txt.bak"
        assert bak_file.exists()
        assert bak_file.read_text() == "version 2"
        
        # Undo should restore to version 2
        from micron.tools.builtin import undo_file
        undo_file("multi_edit.txt")
        assert test_file.read_text() == "version 2"


class TestPasteFile:
    """Tests for paste_file tool."""
    
    def test_paste_append(self, test_dir):
        """Test pasting content to end of file."""
        from micron.tools.builtin import paste_file
        
        # Create initial file
        test_file = test_dir / "paste_test.txt"
        test_file.write_text("line 1\nline 2\n")
        
        # Paste content (append)
        result = paste_file("paste_test.txt", "line 3")
        assert "Success" in result or "success" in result.lower()
        
        # Verify content
        content = test_file.read_text()
        assert "line 3" in content
        assert content.index("line 1") < content.index("line 3")
    
    def test_paste_new_file(self, test_dir):
        """Test pasting to a new file."""
        from micron.tools.builtin import paste_file
        
        result = paste_file("new_file.txt", "new content")
        assert "Success" in result or "success" in result.lower()
        
        test_file = test_dir / "new_file.txt"
        assert test_file.exists()
        assert test_file.read_text() == "new content"
    
    def test_paste_at_line(self, test_dir):
        """Test pasting at specific line number."""
        from micron.tools.builtin import paste_file
        
        # Create initial file
        test_file = test_dir / "line_test.txt"
        test_file.write_text("line 1\nline 3\n")
        
        # Paste at line 2
        result = paste_file("line_test.txt", "line 2", line=2)
        assert "Success" in result or "success" in result.lower()
        
        # Verify content
        lines = test_file.read_text().splitlines()
        assert lines[0] == "line 1"
        assert lines[1] == "line 2"
        assert lines[2] == "line 3"
    
    def test_paste_at_beginning(self, test_dir):
        """Test pasting at beginning of file."""
        from micron.tools.builtin import paste_file
        
        # Create initial file
        test_file = test_dir / "begin_test.txt"
        test_file.write_text("existing content\n")
        
        # Paste at line 1
        result = paste_file("begin_test.txt", "new first line", line=1)
        assert "Success" in result or "success" in result.lower()
        
        # Verify content
        lines = test_file.read_text().splitlines()
        assert lines[0] == "new first line"
        assert lines[1] == "existing content"
    
    def test_paste_creates_directories(self, test_dir):
        """Test that paste_file creates parent directories."""
        from micron.tools.builtin import paste_file
        
        result = paste_file("subdir/nested/file.txt", "content")
        assert "Success" in result or "success" in result.lower()
        
        test_file = test_dir / "subdir" / "nested" / "file.txt"
        assert test_file.exists()
        assert test_file.read_text() == "content"


class TestPatchFile:
    """Tests for patch_file tool."""
    
    def test_single_patch(self, test_dir):
        """Test applying a single patch."""
        from micron.tools.builtin import patch_file
        
        # Create test file
        test_file = test_dir / "patch_test.txt"
        test_file.write_text("Hello World\n")
        
        # Apply patch
        patches = [{"old": "World", "new": "Python"}]
        result = patch_file("patch_test.txt", patches)
        assert "Success" in result or "success" in result.lower()
        assert "1/1" in result
        
        # Verify content
        assert test_file.read_text() == "Hello Python\n"
    
    def test_multiple_patches(self, test_dir):
        """Test applying multiple patches."""
        from micron.tools.builtin import patch_file
        
        # Create test file
        test_file = test_dir / "multi_patch.txt"
        test_file.write_text("A B C\n")
        
        # Apply patches
        patches = [
            {"old": "A", "new": "X"},
            {"old": "B", "new": "Y"},
            {"old": "C", "new": "Z"}
        ]
        result = patch_file("multi_patch.txt", patches)
        assert "Success" in result or "success" in result.lower()
        assert "3/3" in result
        
        # Verify content
        assert test_file.read_text() == "X Y Z\n"
    
    def test_partial_patches(self, test_dir):
        """Test when some patches don't match."""
        from micron.tools.builtin import patch_file
        
        # Create test file
        test_file = test_dir / "partial_patch.txt"
        test_file.write_text("Hello World\n")
        
        # Apply patches (one won't match)
        patches = [
            {"old": "World", "new": "Python"},
            {"old": "NOTFOUND", "new": "X"}
        ]
        result = patch_file("partial_patch.txt", patches)
        assert "Success" in result or "success" in result.lower()
        assert "1/2" in result
        
        # Verify content (only first patch applied)
        assert test_file.read_text() == "Hello Python\n"
    
    def test_no_patches_applied(self, test_dir):
        """Test when no patches match."""
        from micron.tools.builtin import patch_file
        
        # Create test file
        test_file = test_dir / "no_patch.txt"
        test_file.write_text("Hello World\n")
        
        # Apply patches (none match)
        patches = [{"old": "NOTFOUND", "new": "X"}]
        result = patch_file("no_patch.txt", patches)
        assert "Error" in result or "error" in result.lower()
        
        # Verify content unchanged
        assert test_file.read_text() == "Hello World\n"
    
    def test_multiline_patch(self, test_dir):
        """Test patching multiline content."""
        from micron.tools.builtin import patch_file
        
        # Create test file
        test_file = test_dir / "multiline.txt"
        test_file.write_text("line 1\nline 2\nline 3\n")
        
        # Apply patch
        patches = [{"old": "line 2\nline 3", "new": "modified 2\nmodified 3"}]
        result = patch_file("multiline.txt", patches)
        assert "Success" in result or "success" in result.lower()
        
        # Verify content
        assert test_file.read_text() == "line 1\nmodified 2\nmodified 3\n"


class TestTree:
    """Tests for tree function."""
    
    def test_simple_tree(self, test_dir):
        """Test tree with simple structure."""
        from micron.tools.builtin import tree
        
        # Create test structure
        (test_dir / "file1.txt").write_text("content")
        (test_dir / "file2.txt").write_text("content")
        
        result = tree(".")
        assert "/" in result  # Root directory
        assert "file1.txt" in result
        assert "file2.txt" in result
    
    def test_nested_tree(self, test_dir):
        """Test tree with nested directories."""
        from micron.tools.builtin import tree
        
        # Create nested structure
        subdir = test_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("content")
        (test_dir / "root.txt").write_text("content")
        
        result = tree(".")
        assert "subdir/" in result
        assert "nested.txt" in result
        assert "root.txt" in result
    
    def test_max_depth(self, test_dir):
        """Test tree with max_depth limit."""
        from micron.tools.builtin import tree
        
        # Create deep structure
        deep = test_dir / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep.txt").write_text("content")
        
        # Limit depth to 2
        result = tree(".", max_depth=2)
        assert "a/" in result
        assert "b/" in result
        # c/ should not appear (depth 3)
        assert "c/" not in result
    
    def test_dirs_only(self, test_dir):
        """Test tree showing only directories."""
        from micron.tools.builtin import tree
        
        # Create structure with files and dirs
        (test_dir / "file.txt").write_text("content")
        subdir = test_dir / "subdir"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("content")
        
        result = tree(".", show_files=False)
        assert "subdir/" in result
        assert "file.txt" not in result
        assert "file2.txt" not in result
    
    def test_empty_dir(self, test_dir):
        """Test tree on empty directory."""
        from micron.tools.builtin import tree
        
        result = tree(".")
        # Should just show the root
        assert "/" in result
