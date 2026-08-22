import time
import pathlib
from pathlib import Path

from micron.policy import RateLimiter, AuthPolicy, RateLimited
from micron.config import Config, RuntimeConfig


class FakeClock:
    def __init__(self, t=0.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def advance(self, dt: float):
        self.t += float(dt)


def test_rate_limiter_window():
    clock = FakeClock(0.0)
    lim = RateLimiter(max_requests=2, window=60, clock=clock)
    assert lim.allow() is True
    assert lim.allow() is True
    assert lim.allow() is False
    clock.advance(61)
    assert lim.allow() is True


def test_rate_limiter_check_raises():
    clock = FakeClock(0.0)
    lim = RateLimiter(max_requests=1, window=60, clock=clock)
    lim.allow()
    try:
        lim.check()
        assert False, "should have raised"
    except RateLimited as e:
        assert e.retry_after > 0


def test_rate_limiter_disabled():
    lim = RateLimiter.disabled()
    for _ in range(100):
        assert lim.allow() is True


def test_rate_limiter_from_config(tmp_path: Path, monkeypatch):
    # disabled by default
    cfg = Config.__new__(Config)
    cfg._config = {"rate_limits": {"enabled": False}}
    lim = RateLimiter.from_config(cfg)
    assert lim.allow() is True
    cfg._config = {"rate_limits": {"enabled": True, "chat_requests_per_minute": 1}}
    clock = FakeClock(0.0)
    lim2 = RateLimiter.from_config(cfg, clock=clock)
    assert lim2.allow() is True
    assert lim2.allow() is False


def test_auth_policy_disabled():
    pol = AuthPolicy.disabled()
    assert pol.is_valid(None) is True
    assert pol.is_valid("anything") is True


def test_auth_policy_hmac():
    pol = AuthPolicy(api_key="s3cret")
    assert pol.is_valid("s3cret") is True
    assert pol.is_valid("bad") is False
    assert pol.is_valid(None) is False


def test_runtime_config_fake_and_replace(tmp_path: Path):
    rc = RuntimeConfig.fake(tmp_path, provider="ollama", model="llama3")
    assert rc.provider == "ollama"
    assert rc.model == "llama3"
    rc2 = rc.replace(temperature=0.9)
    assert rc2.temperature == 0.9
    assert rc.temperature == 0.1  # frozen copy
    d = rc.as_dict()
    assert d["provider"] == "ollama"
    assert isinstance(d["workdir"], str)


def test_config_runtime_typed(tmp_path: Path):
    cfg = Config.__new__(Config)
    cfg._config = {
        "context_dir": "context",
        "workdir": str(tmp_path),
        "default_provider": "ollama",
        "temperature": 0.2,
        "max_tokens": 1234,
        "max_tool_iterations": 5,
        "host": "127.0.0.1",
        "port": 9000,
        "firecrawl_url": "http://localhost:3002",
        "providers": {"ollama": {"model": "llama3", "base_url": "http://localhost:11434"}},
        "rate_limits": {"enabled": False},
        "authentication": {"enabled": False},
    }
    rt = cfg.runtime()
    assert rt.provider == "ollama"
    assert rt.model == "llama3"
    assert rt.workdir == Path(tmp_path).resolve()
    assert rt.port == 9000
    # shim
    d = cfg.resolve_runtime()
    assert d["provider"] == "ollama"
