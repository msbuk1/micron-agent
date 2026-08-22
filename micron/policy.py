"""Gate policies — RateLimiter + AuthPolicy.

Deep modules hiding: sliding-window deque + hmac constant-time compare.
Single external seam: RateLimiter.from_config / AuthPolicy.from_config,
instance `allow`/`allows` hides window math and hmac.
Local-substitutable via clock injection; per-process in-memory.
"""
from __future__ import annotations

import hmac
import os
import time
import threading
from collections import deque
from dataclasses import dataclass


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"Rate limited: retry after {retry_after:.1f}s")
        self.retry_after = retry_after


class RateLimiter:
    """Sliding-window rate limiter (in-process)."""

    def __init__(self, max_requests: int, window: float = 60.0, *, clock=time.monotonic, maxlen: int = 1000):
        self.max_requests = int(max_requests)
        self.window = float(window)
        self._clock = clock
        self._maxlen = maxlen
        self._times: deque[float] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config, *, clock=time.monotonic) -> "RateLimiter":
        limits = config.get_rate_limits()
        # enabled False -> disabled limiter (allow all)
        if not limits.get("enabled", False):
            return cls.disabled(clock=clock)
        max_req = int(limits.get("chat_requests_per_minute", 60))
        return cls(max_requests=max_req, window=60.0, clock=clock)

    @classmethod
    def disabled(cls, *, clock=time.monotonic) -> "RateLimiter":
        # 0 means allow all (check returns True quickly)
        obj = cls.__new__(cls)
        obj.max_requests = 0
        obj.window = 60.0
        obj._clock = clock
        obj._maxlen = 1000
        obj._times = deque(maxlen=1000)
        obj._lock = threading.Lock()
        return obj

    def _prune(self, now: float) -> None:
        while self._times and now - self._times[0] > self.window:
            self._times.popleft()

    def allow(self) -> bool:
        if self.max_requests == 0:
            return True
        now = self._clock()
        with self._lock:
            self._prune(now)
            if len(self._times) >= self.max_requests:
                return False
            self._times.append(now)
            return True

    def check(self) -> None:
        if not self.allow():
            # compute retry_after
            with self._lock:
                if self._times:
                    oldest = self._times[0]
                    retry = self.window - (self._clock() - oldest)
                else:
                    retry = self.window
            raise RateLimited(retry_after=max(0.0, retry))

    async def __call__(self, request=None) -> None:
        self.check()

    def reset(self) -> None:
        with self._lock:
            self._times.clear()


class AuthPolicy:
    """Hides hmac constant-time compare and header extraction."""

    def __init__(self, api_key: str | None, *, header: str = "x-api-key"):
        self.api_key = api_key
        self.header = header

    @classmethod
    def from_config(cls, config, *, header: str = "x-api-key") -> "AuthPolicy":
        auth = config.get_authentication()
        if not auth.enabled or not auth.api_key_required:
            return cls.disabled()
        # expected key from env
        expected = os.getenv(auth.api_key_env_var, "")
        if not expected:
            # No key configured — deny all (consistent with is_valid_api_key)
            return cls(api_key="__no_key_configured__", header=header)
        return cls(api_key=expected, header=header)

    @classmethod
    def disabled(cls) -> "AuthPolicy":
        return cls(api_key=None)

    def is_valid(self, provided: str | None) -> bool:
        if self.api_key is None:
            return True
        if not provided:
            return False
        # Handle sentinel for missing env
        if self.api_key == "__no_key_configured__":
            return False
        try:
            return hmac.compare_digest(provided, self.api_key)
        except Exception:
            return False

    def allows(self, request) -> bool:
        # Extract from header or query param api_key
        provided = None
        try:
            # Starlette/FastAPI Request
            provided = request.headers.get(self.header) or request.headers.get(self.header.upper()) or request.headers.get("X-API-KEY")
            if not provided and hasattr(request, "query_params"):
                provided = request.query_params.get("api_key")
        except Exception:
            pass
        return self.is_valid(provided)

    def check(self, request) -> None:
        if not self.allows(request):
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Unauthorized - API key required")

    async def __call__(self, request) -> None:
        self.check(request)
