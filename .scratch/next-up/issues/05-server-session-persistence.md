# 6 — Server writes to context/sessions/ during chat

**GitHub:** https://github.com/msbuk1/micron-agent/issues/6
**Labels:** `enhancement`, `ready-for-agent`

## What to build

The server's chat handler persists each turn to `context/sessions/` via the existing `SessionLogger` (currently CLI-only). After this ticket, a chat exchange via the web UI produces a JSONL session file with the user turn and the assistant turn — matching what the CLI does today.

## Blocked by

None — uses the existing `SessionLogger` from `micron/sessions.py`.

## Acceptance criteria

- [ ] After a web-UI chat exchange, a JSONL file appears in `context/sessions/`
- [ ] The file contains the user message and the assistant response
- [ ] The CLI session log format is unchanged (no regression)
- [ ] All existing tests pass
