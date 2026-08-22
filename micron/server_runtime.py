"""ServerRuntime — deep module hiding server wiring.

Ergonomic C shape: zero-arg ServerRuntime().app for 80% path,
progressive injection for tests.
Local-substitutable via tmp_path + Fake agent/limiter/auth.
"""
from __future__ import annotations

from pathlib import Path

from micron.config import Config, RuntimeConfig
from micron.policy import RateLimiter, AuthPolicy
from micron.sessions import SessionLogger


class ServerRuntime:
    def __init__(
        self,
        config: Config | RuntimeConfig | None = None,
        *,
        agent=None,
        sessions: SessionLogger | None = None,
        limiter: RateLimiter | None = None,
        auth: AuthPolicy | None = None,
    ):
        if isinstance(config, RuntimeConfig):
            self._config = None
            self.runtime = config
        else:
            self._config = config or Config()
            self.runtime = self._config.runtime()
        # agent
        if agent is not None:
            self.agent = agent
        else:
            from micron.agent import create_agent

            self.agent = create_agent(**self.runtime.for_agent())
            # backend
            try:
                from micron.llm import create_backend

                backend = create_backend(**self.runtime.for_backend())
                self.agent.llm = backend
            except Exception:
                pass
        # sessions
        if sessions is not None:
            self.sessions = sessions
        else:
            try:
                sessions_dir = Path(self.runtime.context_dir) / "sessions"
                sl = SessionLogger(sessions_dir)
                sl.start_session()
                self.sessions = sl
            except Exception:
                self.sessions = None
        # gate policies
        if limiter is not None:
            self.limiter = limiter
        else:
            try:
                self.limiter = RateLimiter.from_config(self._config) if self._config else RateLimiter.disabled()
            except Exception:
                self.limiter = RateLimiter.disabled()
        if auth is not None:
            self.auth = auth
        else:
            try:
                self.auth = AuthPolicy.from_config(self._config) if self._config else AuthPolicy.disabled()
            except Exception:
                self.auth = AuthPolicy.disabled()

    @classmethod
    def load(cls, config_path: str | None = None, **overrides) -> "ServerRuntime":
        cfg = Config(config_path=config_path)
        rt = cfg.runtime()
        if overrides:
            rt = rt.replace(**overrides)
        return cls(config=rt)

    @property
    def config(self) -> Config | None:
        return self._config
