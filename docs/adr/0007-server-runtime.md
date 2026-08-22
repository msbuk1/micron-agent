# ADR 0007 — ServerRuntime deep module

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** codebase review (design-it-twice P7)
- **Origin:** remaining shallow — `micron/server.py:27` globals `agent`, `session_logger`, `_config_cache`, `chat_request_times:deque(maxlen=1000)` + `check_authentication:41`/`check_rate_limit:61` + `lifespan:89` 40-line wiring

## Context

After `RuntimeConfig` (`config.py:36`) + `RateLimiter`/`AuthPolicy` (`policy.py:1`) landed, `server.py` still owned mutable globals and free functions reading `Config` on each request. `lifespan` wired `Config→RuntimeConfig→create_agent→create_backend` + `SessionLogger` manually; `check_rate_limit` did `while now - deque[0] > 60: popleft` with `time.time()` (not mockable `clock`), `check_authentication` did `hmac.compare_digest` with `X-API-KEY`/`?api_key` extraction. Testing without `TestClient` + `time.sleep` was hard; per-process vs Redis port not isolated.

## Decision

`micron/server_runtime.py:1` ergonomic wrapper:

```python
class ServerRuntime:
    def __init__(self, config: Config|RuntimeConfig|None=None, *, agent=None, sessions=None, limiter=None, auth=None): ...
    @classmethod def load(cls, config_path=None, **overrides) -> Self: ...  # Config(path).runtime().replace(**)
    # owns: runtime:RuntimeConfig, agent:MicronAgent, sessions:SessionLogger|None, limiter:RateLimiter, auth:AuthPolicy
```

Delegates to `RuntimeConfig.from_config(cfg)` → `create_agent(**rt.for_agent())` + `SessionLogger(rt.context_dir/"sessions")` + `RateLimiter.from_config` / `AuthPolicy.from_config`. No `RedisStore` port yet — per-process `deque` + `hmac` remain inside `policy.py`; `clock` + `tmp_path` remain local-substitutable (one adapter=hypothetical deferred per ADR 0005). `server.py` keeps `check_authentication`/`check_rate_limit` as shims calling `policy` for compat; preferred is `Depends(auth)`/`Depends(limiter)` via `policy.py:RateLimiter.__call__`.

Rejected: (B) 22-method `ServerRuntime` builder with `with_agent_factory/with_redis_rate_limit/with_jwt_auth/with_sessions_db` + 4 protocols `AgentResolver/SessionStore/RateStore/AuthScheme` — many hypothetical ports; (A) single `Gate(verify+allow)` merging 401/429 — conflates HTTP mappings. Chose C: zero-arg `ServerRuntime().app` 80% path, injection for tests (`ServerRuntime(config=Config.fake(tmp_path), agent=Fake, limiter=RateLimiter.disabled())`).

## Consequences

### Positive

- **Locality** — wiring, `deque` window, `hmac` behind `server_runtime`+`policy` vs scattered `server.py`; fix once.
- **Testability** — `ServerRuntime` with `FakeClock`/`tmp_path` without `TestClient` + `time`.
- **Depth** — one construction hides 14-key hoisting + session dir + gate state.

### Negative

- `server.py` globals remain as shims until callers migrate to `ServerRuntime` + `Depends`; two spellings coexist one release.
- Per-process limiter only — restart clears `deque`; distributed limit needs new `Store` port (deferred).
- `ServerRuntime` mutable (`agent` swap) — not frozen like `RuntimeConfig`; documented as runtime owner, not value.
