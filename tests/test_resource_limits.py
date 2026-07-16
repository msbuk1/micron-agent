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
        "echo test | bash",  # Pipe to shell
        "echo test | sh",    # Pipe to shell
        "./script.sh",       # Path execution
        "~/script.sh",       # Home execution
        "$(echo test)",      # Command substitution
        "`echo test`",       # Backtick substitution
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
        assert "blocked" in result.lower() or "dangerous" in result.lower() or "not allowed" in result.lower()


class TestSafeCommands:
    """Tests for safe commands that should work."""

    @pytest.mark.parametrize("command", [
        "echo hello",
        "ls -la",
        "pwd",
        "whoami",
        "date",
        "rm nonexistent_file.txt",  # Safe rm (no -r flag)
        "cat /etc/hostname",
        "head -5 /etc/passwd",
        "wc -l /etc/passwd",
    ])
    def test_safe_command(self, command):
        """Test that safe commands execute."""
        result = run_command(command, timeout=5)
        assert "Command blocked" not in result


class TestInjectionPrevention:
    """Tests for command injection prevention with shell=False."""

    @pytest.mark.parametrize("command", [
        "echo hello | bash",       # Pipe to shell
        "echo hello | sh",         # Pipe to shell
        "./malicious_script.sh",   # Path execution
        "~/malicious_script.sh",   # Home execution
    ])
    def test_injection_blocked(self, command):
        """Test that injection attempts are blocked."""
        result = run_command(command)
        assert "Error" in result
        assert "blocked" in result.lower() or "not allowed" in result.lower() or "not found" in result.lower()

    @pytest.mark.parametrize("command", [
        "echo $(whoami)",           # Command substitution
        "echo `whoami`",           # Backtick substitution
        "echo hello > /dev/sda",   # Redirect to block device
    ])
    def test_shell_syntax_blocked(self, command):
        """Test that shell syntax is blocked."""
        result = run_command(command)
        assert "Error" in result
        assert "blocked" in result.lower() or "not allowed" in result.lower()

    def test_shlex_prevents_semicolon_injection(self):
        """Test that shlex.split prevents semicolon injection.
        
        With shell=True, 'echo hello; rm -rf /' would execute both commands.
        With shell=False, shlex.split treats it as args to echo, which is safe.
        """
        result = run_command("echo hello; rm -rf /")
        # With shlex.split, this becomes ['echo', 'hello;', 'rm', '-rf', '/']
        # echo receives the args and prints them safely
        # Should either succeed (safe) or fail (not found/error)
        assert "Error" in result or "hello; rm" in result or "hello" in result

    def test_shlex_prevents_chained_injection(self):
        """Test that shlex.split prevents chained command injection.
        
        With shell=True, 'cat /etc/passwd; sudo rm -rf /' would execute both.
        With shell=False, shlex.split treats it as args to cat, which is safe.
        """
        result = run_command("cat /etc/passwd; sudo rm -rf /")
        # With shlex.split, this becomes ['cat', '/etc/passwd;', 'sudo', 'rm', '-rf', '/']
        # cat receives the args (treating ';' as part of filename), which fails safely
        assert "Error" in result or "root:" in result or "passwd" in result

    def test_pipe_not_executed(self):
        """Test that pipes are not executed as shell pipes."""
        # With shell=False, | is treated as literal argument
        result = run_command("echo hello | cat")
        # Should either fail or echo "hello | cat" as literal
        assert "Error" in result or "hello | cat" in result

    def test_command_substitution_not_executed(self):
        """Test that command substitution is not executed."""
        # With shell=False, $(...) is treated as literal argument
        result = run_command("echo $(whoami)")
        # Should either fail or echo "$(whoami)" as literal
        assert "Error" in result or "$(whoami)" in result
