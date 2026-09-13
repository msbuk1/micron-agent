# 06 — Remove ServerRuntime.load() compat shim

**GitHub:** https://github.com/msbuk1/micron-agent/issues/26
**Labels:** `ready-for-agent`

## What to build

The unused server-runtime loading shim is gone and nothing references it. Verify no caller (production, tests, docs) uses the old load path, delete it, and update any docs that mention it. Demo: grep shows zero references; full suite green.

Left behind by the profiles-composition ticket, which routed all boot paths through the composition.

## Blocked by

None — can start immediately.

## Acceptance criteria

- [ ] Zero references to the shim in code, tests, and docs
- [ ] Shim deleted; full suite green
- [ ] No behavior change
