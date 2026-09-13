# 04 — Scoped tools per agent (isolated registry view)

**GitHub:** https://github.com/msbuk1/micron-agent/issues/18
**Labels:** `ready-for-agent`

## What to build

One session/agent can run with a different capability set than the global registry (e.g. plan mode or a subagent with a reduced toolset) while the default session keeps the full set. Scoping is enforced at the tool pipeline, not by if-checks at call sites. Demo: compose an agent preset with 3 of 24 tools, run it, and show the model only sees those 3 schemas while the main session still sees all 24.

Port of the deepseek-harness agent-preset + isolate-realm idea. Uses ToolRegistry + SkillLoader prompt assembly; enforcement lives in the waterfall pipeline ticket.

## Blocked by

- 01 — Waterfall tool pipeline (#15). Needs the pipeline enforcement point.

## Acceptance criteria

- [ ] An agent preset composes a scoped tool view; scoping is a first-class composition input, not a filter hacked into the prompt
- [ ] Out-of-scope calls are rejected by the pipeline even if the model hallucinates them
- [ ] Prompt assembly only advertises in-scope schemas
- [ ] Tests cover full-set default, reduced preset, and rejected out-of-scope call
