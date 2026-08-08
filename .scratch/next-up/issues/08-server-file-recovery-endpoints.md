# 9 — Server file-recovery endpoints

**GitHub:** https://github.com/msbuk1/micron-agent/issues/9
**Labels:** `enhancement`, `ready-for-agent`

## What to build

Add four server endpoints that wrap the existing `builtin.py` recovery tool functions: `GET /trash` (list), `POST /restore` (restore a file), `POST /purge` (empty trash), `POST /undo` (restore from `.bak`). The web UI can then list, restore, purge, and undo files — matching the CLI's `/trash`, `/restore`, `/purge`, `/undo` commands.

## Blocked by

None — independent of the session work. Shares the SlashCommandRegistry work but doesn't depend on it.

## Acceptance criteria

- [ ] `GET /trash` returns the list of recoverable files
- [ ] `POST /restore` with a filename restores that file from `.trash/`
- [ ] `POST /purge` empties the trash directory
- [ ] `POST /undo` with a filename restores the file from its `.bak` backup
- [ ] All existing tests pass
