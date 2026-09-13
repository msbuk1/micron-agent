# 05 — Unified execution seam (fs + subprocess share one world)

**GitHub:** https://github.com/msbuk1/micron-agent/issues/19
**Labels:** `ready-for-agent`

## What to build

File tools and shell execution share one swappable execution world behind a single seam (service definition / provider / consumer — all three, never one role alone). Pointing the seam at a remote sandbox moves file reads/writes, shell, and any future terminal/LSP consumers together, with no provider forks. Demo: flip the provider from local to a fake remote in config and show run_command plus file tools both route through it, with sandbox argv-wrapping applied once in the tool pipeline.

Unifies the WorkspaceFS containment/verify/trash lifecycle with the run_command policy + resource limits. Consumers wrap argv before spawning; policy listens on pipeline events rather than importing the loop.

## Blocked by

- 01 — Waterfall tool pipeline (#15). Needs the pre-execute wrap point.

## Acceptance criteria

- [ ] One seam owns the execution world; WorkspaceFS and shell consumers both resolve through it
- [ ] Swapping the provider moves all consumers together (proven by a fake provider in tests)
- [ ] Sandbox confinement wraps argv once, before spawn, via the pipeline — not per-tool
- [ ] Existing traversal guards, blocklist, and resource limits still hold; tests cover local + fake-remote
