# ADR 0005 — RuntimeConfig + RateLimiter / AuthPolicy

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** codebase review (design-it-twice P3)
- **Origin:** P3 candidate — `Config.resolve_runtime:299` untyped `dict` + `server.py:27` globals `chat_request_times:deque` / `check_rate_limit` / `check_authentication` wide `Config` surface

## Context

`Config.resolve_runtime` returned a 14-key flat `dict` hoisting `providers[provider]` (`api_key/base_url/n_threads…` `config.py:312-328` + `_deep_merge`/`_apply_env_vars` + env precedence) — callers did `rt["provider"]` with magic keys and no validation. `Config` itself had `get/get_provider_config/get_rate_limits/get_resource_limits/get_authentication/is_valid_api_key`. `server.py` had mutable module globals `chat_request_times = deque(maxlen=1000)` + `check_rate_limit` (60s sliding `while now - deque[0] > 60: popleft` `server.py:76-78`) and `check_authentication` (`hmac.compare_digest` `config.py:419`, header `X-API-KEY`/`?api_key`). No injection, hard to test without `time.sleep`/`monkeypatch`.

## Decision

`micron/config.py:36` + `micron/policy.py:1`:

```python
@dataclass(frozen=True) class RuntimeConfig: provider,model,api_key,base_url,temperature,max_tokens,max_tool_iterations,workdir:Path,context_dir:Path,firecrawl_url,host,port,n_threads,n_ctx,n_gpu_layers
class RuntimeConfig: as_dict()->dict, for_agent()->dict, for_backend()->dict, replace(**overrides)->Self, fake(tmp_path)->Self
class Config: runtime(provider_override, model_override)->RuntimeConfig; resolve_runtime(...)->dict = runtime().as_dict() shim; to_dict()->dict

class RateLimited(Exception): retry_after: float
class RateLimiter: __init__(max_requests, window=60, *, clock=time.monotonic, maxlen=1000), from_config(config), disabled(), allow()->bool, check()->None(raises RateLimited), async __call__(request)->None, reset()
class AuthPolicy: __init__(api_key, header="x-api-key"), from_config(config), disabled(), is_valid(provided)->bool, allows(request)->bool, check(request)->None(raises 401), async __call__(request)->None
```

`Config.runtime()` hides provider hoisting, `Path.resolve`, defaults; callers learn `rt.provider` typed. `RateLimiter`/`AuthPolicy` hide deque+`Lock` window + `hmac.compare_digest` + header normalization; `clock` injectable for `FakeClock` tests. Per-process in-memory; no `RedisStore` port yet (one adapter=hypothetical — deferred). `server.py` shims keep `check_rate_limit`/`check_authentication` calling new classes for compat; preferred is `Depends(auth)`/`Depends(limiter)` + `create_agent(**rt.for_agent())`.

Rejected: (B) `RuntimeConfig` split into `GenerationSpec/ProviderSpec/PathSpec/ServerSpec` + `RateLimitStore(Protocol)`/`AuthVerifier` ports + `Tiered`/`Bearer` — many hypothetical seams; (A) single `Gate(verify+allow)` merging 401/429 — conflates two HTTP mappings. Chose ergonomic C: typed viewport + two separate `Depends`-compatible gate policies.

## Consequences

### Positive

- **Depth** — one `Config.runtime()` → 14 attrs validated once; one `limiter.allow()` hides window math.
- **Locality** — provider hoisting in `config.py`, window math in `policy.py:RateLimiter._prune`, hmac in `AuthPolicy.is_valid`.
- **Testability** — `RuntimeConfig.fake(tmp_path)`, `RateLimiter(clock=FakeClock)`, `AuthPolicy(api_key="s").is_valid()` — no yaml file, no sleep.

### Negative

- `RuntimeConfig` frozen dataclass — `replace(**overrides)` required for mutation vs `rt.port=0`; idiomatic but new.
- `RateLimiter` per-process only — restart clears state, not distributed; documented.
- `resolve_runtime` kept as shim to avoid breaking callers; two spellings coexist until callers migrate to `runtime()`.
