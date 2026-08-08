# 7 — Server session endpoints

**GitHub:** https://github.com/msbuk1/micron-agent/issues/7
**Labels:** `enhancement`, `ready-for-agent`

## What to build

Add three server endpoints: `GET /sessions` (list), `GET /session/{id}` (read), `POST /session/{id}/resume` (resume). The web UI can then list past sessions, view a session's history, and resume a session by ID.

## Blocked by

#6 — the server must persist to `context/sessions/` before these endpoints make sense.

## Acceptance criteria

- [ ] `GET /sessions` returns a list of recent sessions
- [ ] `GET /session/{id}` returns the session's turns
- [ ] `POST /session/{id}/resume` accepts a session id and continues that conversation
- [ ] All existing tests pass
