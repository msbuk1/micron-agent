"""Tests for resource limits in run_command."""
import pytest

from micron.tools.builtin import run_command


class TestCommandLengthLimit:
    """Tests for command length limit (500 characters)."""

    def test_command_under_limit(self):
        """Test that commands under 500 chars work."""
        cmd = "echo " + "a" * 40
        result = run_command(cmd)
        assert "Command blocked" not in result

    def test_command_over_limit(self):
        """Test that commands over 500 chars are blocked."""
        cmd = "echo " + "a" * 496  # 501 chars total
        result = run_command(cmd)
        assert "Error" in result
        assert "too long" in result.lower() or "500" in result


class TestCommandBlocklist:
    """Tests for dangerous command blocklist."""

    @pytest.mark.parametrize("command", [
        "rm -rf /",
        "sudo su",
        "sudo bash",
        "mkfs /dev/sda",
        "dd if=/dev/zero",
        "echo test | bash",
        "echo test | sh",
        "./script.sh",
        "~/script.sh",
        "$(echo test)",
        "`echo test`",
        "apt-get install package",
        "yum install package",
        "chsh",
        "useradd test",
        "userdel test",
        "passwd",
    ])
    def test_blocklist_pattern(self, command):
        """Test that dangerous commands are blocked."""
        result = run_command(command)
        assert "Error" in result
        assert "blocked" in result.lower() or "dangerous" in result.lower()


class TestSafeCommands:
    """Tests for safe commands that should work."""

    @pytest.mark.parametrize("command", [
        "echo hello",
        "ls -la",
        "pwd",
        "whoami",
        "date",
    ])
    def test_safe_command(self, command):
        """Test that safe commands execute."""
        result = run_command(command, timeout=5)
        assert "Command blocked" not in result
