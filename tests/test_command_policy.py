"""Tests for CommandPolicy (micron.tools.command_policy)."""
import os

import pytest

from micron.tools.command_policy import (
    Allow,
    CommandPolicy,
    Deny,
    Limit,
)


@pytest.fixture
def policy():
    """Fresh CommandPolicy for each test."""
    return CommandPolicy()


class TestAllowCases:
    """Commands that should be permitted."""

    def test_echo(self, policy):
        assert isinstance(policy.evaluate(["echo", "hello"]), Limit)

    def test_ls(self, policy):
        assert isinstance(policy.evaluate(["ls", "-la"]), Limit)

    def test_pwd(self, policy):
        assert isinstance(policy.evaluate(["pwd"]), Limit)

    def test_safe_rm(self, policy):
        assert isinstance(policy.evaluate(["rm", "file.txt"]), Limit)

    def test_empty_args_denied(self, policy):
        d = policy.evaluate([])
        assert isinstance(d, Deny)

    def test_cat(self, policy):
        assert isinstance(policy.evaluate(["cat", "/etc/passwd"]), Limit)


class TestBlocklist:
    """Blocked command names."""

    @pytest.mark.parametrize("cmd", [
        ["sudo", "su"],
        ["sudo", "bash"],
        ["mkfs", "/dev/sda"],
        ["dd", "if=/dev/zero"],
        ["chown", "root", "/tmp/x"],
        ["chmod", "777", "/tmp/x"],
        ["chsh"],
        ["useradd", "test"],
        ["userdel", "test"],
        ["passwd"],
        ["wget", "http://evil.com"],
        ["curl", "http://evil.com"],
        ["apt-get", "install", "x"],
        ["yum", "install", "x"],
        ["pacman", "-S", "x"],
    ])
    def test_blocked(self, policy, cmd):
        d = policy.evaluate(cmd)
        assert isinstance(d, Deny)
        assert "blocked" in d.reason.lower()

    def test_rm_rf_blocked(self, policy):
        d = policy.evaluate(["rm", "-rf", "/"])
        assert isinstance(d, Deny)

    def test_rm_r_flag_blocked(self, policy):
        d = policy.evaluate(["rm", "-r", "dir/"])
        assert isinstance(d, Deny)

    def test_rm_recursive_upper_R(self, policy):
        d = policy.evaluate(["rm", "-R", "dir/"])
        assert isinstance(d, Deny)


class TestFlagScanning:
    """Dangerous flags / patterns in any argument position."""

    def test_pipe_blocked(self, policy):
        d = policy.evaluate(["echo", "hello", "|", "cat"])
        assert isinstance(d, Deny)
        assert "pipe" in d.reason.lower()

    def test_dot_slash_blocked(self, policy):
        d = policy.evaluate(["./script.sh"])
        assert isinstance(d, Deny)
        assert "blocked" in d.reason.lower()

    def test_tilde_slash_blocked(self, policy):
        d = policy.evaluate(["~/script.sh"])
        assert isinstance(d, Deny)
        assert "blocked" in d.reason.lower()

    def test_dollar_paren_blocked(self, policy):
        d = policy.evaluate(["echo", "$(whoami)"])
        assert isinstance(d, Deny)
        assert "blocked" in d.reason.lower()

    def test_backtick_blocked(self, policy):
        d = policy.evaluate(["echo", "`whoami`"])
        assert isinstance(d, Deny)
        assert "blocked" in d.reason.lower()

    def test_dev_sd_blocked(self, policy):
        d = policy.evaluate(["echo", "x", ">", "/dev/sda"])
        assert isinstance(d, Deny)
        assert "blocked" in d.reason.lower()

    def test_dev_nvme_blocked(self, policy):
        d = policy.evaluate(["dd", "of=/dev/nvme0n1"])
        assert isinstance(d, Deny)
        assert "blocked" in d.reason.lower()

    @pytest.mark.parametrize("shell", ["bash", "sh", "zsh"])
    def test_shell_name_blocked(self, policy, shell):
        d = policy.evaluate(["echo", "x", shell])
        assert isinstance(d, Deny)
        assert "bash/sh/zsh" in d.reason.lower()


class TestUnrestrictedMode:
    """MICRON_UNRESTRICTED skips blocklist and flag checks."""

    def test_unrestricted_allows_sudo(self, policy, monkeypatch):
        monkeypatch.setenv("MICRON_UNRESTRICTED", "1")
        d = policy.evaluate(["sudo", "something"])
        assert isinstance(d, Limit)

    def test_unrestricted_allows_pipe(self, policy, monkeypatch):
        monkeypatch.setenv("MICRON_UNRESTRICTED", "true")
        d = policy.evaluate(["echo", "x", "|", "cat"])
        assert isinstance(d, Limit)

    def test_unrestricted_allows_rm_rf(self, policy, monkeypatch):
        monkeypatch.setenv("MICRON_UNRESTRICTED", "yes")
        d = policy.evaluate(["rm", "-rf", "/"])
        assert isinstance(d, Limit)

    def test_restricted_blocks_sudo(self, policy, monkeypatch):
        monkeypatch.delenv("MICRON_UNRESTRICTED", raising=False)
        d = policy.evaluate(["sudo", "something"])
        assert isinstance(d, Deny)


class TestDataclassBehaviour:
    """Verify Decision dataclass contracts."""

    def test_deny_is_frozen(self):
        d = Deny(reason="nope")
        with pytest.raises(AttributeError):
            d.reason = "changed"  # type: ignore[misc]

    def test_limit_defaults(self):
        lim = Limit()
        assert lim.cpu is None
        assert lim.memory is None
        assert lim.procs is None
        assert lim.files is None

    def test_limit_custom(self):
        lim = Limit(cpu=30, memory=256, procs=10, files=50)
        assert lim.cpu == 30
        assert lim.memory == 256

    def test_allow_is_frozen(self):
        a = Allow()
        with pytest.raises(AttributeError):
            a.x = 1  # type: ignore[attr-defined]
