# 8 — Server operational endpoints (info)

**GitHub:** https://github.com/msbuk1/micron-agent/issues/8
**Labels:** `enhancement`, `ready-for-agent`

## What to build

Add four server endpoints that mirror CLI capabilities the web app is currently missing: `POST /clear` (clear history), `GET /model` (current model info), `GET /providers` (configured providers), `POST /unload` (unload model from RAM).

## Blocked by

None — independent of the session work.

## Acceptance criteria

- [ ] `POST /clear` clears the agent's in-memory history
- [ ] `GET /model` returns provider name and model name
- [ ] `GET /providers` returns the list of configured providers
- [ ] `POST /unload` unloads the model from RAM
- [ ] All existing tests pass
