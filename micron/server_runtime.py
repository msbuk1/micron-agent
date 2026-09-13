"""ServerRuntime — deep module hiding server wiring.

Ergonomic C shape: zero-arg ServerRuntime().app for 80% path,
progressive injection for tests.
Local-substitutable via tmp_path + Fake agent/limiter/auth.
"""
from __future__ import annotations

from pathlib import Path

from micron.config import Config, RuntimeConfig
from micron.policy import AuthPolicy, RateLimiter
from micron.sessions import SessionLogger


class ServerRuntime:
    def __init__(
        self,
        config: Config | RuntimeConfig | None = None,
        *,
        agent=None,
        sessions: SessionLogger | None | bool = None,
        limiter: RateLimiter | None = None,
        auth: AuthPolicy | None = None,
        preset: str | None = None,
    ):
        if isinstance(config, RuntimeConfig):
            self._config = None
            self.runtime = config
        else:
            self._config = config or Config()
            self.runtime = self._config.runtime()
        self.preset = preset
        # sessions — None means "create default", False means "explicitly
        # disabled" (headless profiles), a SessionLogger is used as-is.
        # Created before the agent so it can be injected at construction
        # (issue #25): the log is the authority from the first turn.
        if sessions is False:
            self.sessions = None
        elif sessions is not None:
            self.sessions = sessions
        else:
            try:
                sessions_dir = Path(self.runtime.context_dir) / "sessions"
                sl = SessionLogger(sessions_dir)
                sl.start_session()
                self.sessions = sl
            except Exception:
                self.sessions = None
        # agent
        if agent is not None:
            self.agent = agent
            # Injected agents still get the logger when they accept one and
            # don't already hold an active session (issue #25).
            if self.sessions is not None and getattr(agent, "sessions", None) is None:
                try:
                    agent.sessions = self.sessions
                except Exception:
                    pass
        else:
            from micron.agent import create_agent

            if preset is not None and preset != "default":
                # Scoped preset: compose a ScopedToolRegistry view over the
                # full set and inject it (issue #22). The default path is
                # untouched — the agent seeds its own registry.
                from micron.profiles import compose_tools, full_registry

                tools = compose_tools(full_registry(), preset)
                self.agent = create_agent(**self.runtime.for_agent(), tools=tools, sessions=self.sessions)
            else:
                self.agent = create_agent(**self.runtime.for_agent(), sessions=self.sessions)
            # backend
            try:
                from micron.llm import create_backend

                backend = create_backend(**self.runtime.for_backend())
                self.agent.llm = backend
            except Exception:
                pass
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

    @property
    def config(self) -> Config | None:
        return self._config
