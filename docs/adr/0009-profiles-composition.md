# ADR 0009 — Profiles composition (one boot path, ordered patch layers)

## Status

Accepted

## Context

Every entry point (CLI one-shot, TUI, HTTP server, headless runner) needs
the same thing: a resolved runtime config, a tool scope, and a wired
agent + session logger + gate policies. Before profiles, each transport
did its own wiring, so "how is the agent booted?" had as many answers as
there were entry points, and there was no single place to see — or
override — the resolved configuration. Two earlier decisions constrain
the shape: `RuntimeConfig` is the typed viewport over `Config` (ADR
0005), and `ServerRuntime` is the deep module that owns agent/sessions/
limiter/auth wiring (ADR 0007). The profiles layer must compose those,
not duplicate them.

## Decision

`micron/profiles.py` is the single boot composition for every entry
point. No parallel loader: `boot` delegates to `ServerRuntime` (ADR
0005/0007).

- **Named profiles over one boot path.** `PROFILE_PATCHES` maps
  canonical names (`default`, `tui`, `server`, `headless`) to thin
  patches — a profile only sets the rows that distinguish it from the
  base. `canonical_profile` resolves aliases (`one-shot` → `default`,
  `interactive` → `tui`); unknown names raise `ValueError`. Profile
  differences that are boot-level rather than config-level (headless has
  no session logger) are applied by callers via `boot(...,
  sessions=False)`, not by a separate wiring path.
- **Ordered patch layers.** `build_composition` applies layers
  deterministically: base (CLI flag overrides for
  provider/model/temperature/max_tokens) → profile patch → home patch
  (the `profiles:` section of micron.yaml) → `--patch` overlay file.
  Later layers win.
- **Whole-row replace-or-insert by id.** `apply_patch_layer` replaces
  each patched row wholesale (scalar or dict) or inserts a new one —
  never a deep merge. Unknown rows raise `ValueError` listing the valid
  rows, so typos fail loudly instead of silently doing nothing.
- **Preset as a first-class boot input** (issues #18, #22). The
  composition carries the resolved preset name (`canonical_preset`
  validates; unknown names fail loudly). `boot` hands it to
  `ServerRuntime`, which composes the agent's tools via
  `compose_tools(full_registry(), preset)` — a `ScopedToolRegistry` view
  for scoped presets (e.g. `plan`), the unscoped path for `default`/`None`.
  Scoping is enforced in the waterfall pipeline (ADR 0008), not by
  filtering the prompt.
- **`--dump-config` as the introspection seam.** `Composition.as_dict()`
  prints the resolved composition — profile, preset, effective toolset
  (`effective_tools`, no agent boot required), the ordered layer list,
  and the runtime rows with `api_key` redacted — so any row can be
  targeted by a patch and verified without booting.

## Consequences

- One wiring to review: a change to boot semantics lands in
  `ServerRuntime`/`profiles.py` once and every transport inherits it.
- Patch semantics are deliberately shallow (whole-row replace). Users
  who want to tweak one key inside a dict row must restate the row;
  in exchange, layer order is fully predictable and `--dump-config`
  shows exactly what each layer contributed.
- Unknown rows, unknown profiles, and unknown presets all fail loudly at
  composition time — misconfiguration never boots a silently-wrong agent.
- New entry points are a profile name plus a transport, not a new loader.
- `--dump-config` redacts `api_key`; the resolved composition is safe to
  paste into bug reports.
