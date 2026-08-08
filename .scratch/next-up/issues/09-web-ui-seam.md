# 10 — Web UI seam — serve micron/static/

**GitHub:** https://github.com/msbuk1/micron-agent/issues/10
**Labels:** `enhancement`, `ready-for-agent`

## What to build

The web UI is currently a 250-line `HTML_PAGE` Python string in `micron/server.py` with inline JS+CSS. The JS implements a second, divergent copy of the event handler that `process_events` already implements on the server. `micron/static/{index.html,app.js,style.css}` exists but is dead code — never mounted.

Wire the static directory as the UI source. Delete the inline `HTML_PAGE` from `server.py`. The JS implements an `EventRenderer` interface — one method per event type — so the SSE consumer has a single source of truth.

## Blocked by

None — independent of the other work.

## Acceptance criteria

- [ ] `GET /` serves `micron/static/index.html` (no more inline `HTML_PAGE` in `server.py`)
- [ ] The inline JS is moved to `micron/static/app.js` as an `EventRenderer` class
- [ ] CSS is moved to `micron/static/style.css`
- [ ] `server.py` reads top-to-bottom for HTTP only — no UI markup
- [ ] All existing tests pass
