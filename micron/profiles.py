"""Profiles — one boot composition for every entry point (CLI, TUI, server).

Port of the deepseek-harness profiles/bundles idea, at micron size:

- ``Composition`` is the resolved boot tree: a ``RuntimeConfig`` plus the
  profile name and the ordered patch layers that produced it.
- ``build_composition`` applies patch layers deterministically:
  base composition → profile patch → home patch → ``--patch`` overlay.
  Later layers replace whole rows by id or insert new rows.
- ``boot`` composes agent + sessions + limiter/auth through ``ServerRuntime``
  — the single wiring every profile shares. No parallel loader: RuntimeConfig
  and ServerRuntime stay the typed viewport the profiles compose (ADR 0005/0007).

``--dump-config`` prints the resolved composition so any row can be patched.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from micron.config import Config, RuntimeConfig

# ── Patch layers ─────────────────────────────────────────────────────────

def apply_patch_layer(rt: RuntimeConfig, patch: dict) -> RuntimeConfig:
    """Apply one ordered patch layer to a RuntimeConfig.

    Deterministic: each key in the patch replaces the whole row (scalar or
    dict) or inserts a new one. Unknown keys raise ``ValueError`` so typos
    fail loudly instead of silently doing nothing.
    """
    valid = set(rt.as_dict().keys())
    unknown = set(patch.keys()) - valid
    if unknown:
        raise ValueError(
            f"Unknown config row(s): {sorted(unknown)}. "
            f"Valid rows: {sorted(valid)}"
        )
    return rt.replace(**patch)


# ── Named profiles ───────────────────────────────────────────────────────

#: Per-profile patches over the base composition. Thin compositions —
#: no plugin tree, no parallel loader. A profile only sets the rows that
#: distinguish it from the base.
PROFILE_PATCHES: dict[str, dict] = {
    # CLI one-shot / default — the base composition, no extra rows.
    "default": {},
    "one-shot": {},
    # TUI / interactive — same wiring, session logging on (the boot default).
    "tui": {},
    "interactive": {},
    # HTTP server — same wiring; host/port come from config or CLI flags.
    "server": {},
    # Headless one-shot runner — same composition; the boot-level difference
    # (no session logger) is applied by callers via boot(..., sessions=False).
    "headless": {},
}

#: Aliases so ``--profile tui`` and ``--profile interactive`` are the same
#: composition. Canonical names are the keys of PROFILE_PATCHES.
PROFILE_ALIASES: dict[str, str] = {
    "one-shot": "default",
    "interactive": "tui",
}


def canonical_profile(name: str | None) -> str:
    """Resolve a profile alias to its canonical name."""
    if name is None:
        return "default"
    canonical = PROFILE_ALIASES.get(name, name)
    if canonical not in PROFILE_PATCHES:
        raise ValueError(
            f"Unknown profile: {name!r}. Known profiles: {sorted(PROFILE_PATCHES)}"
        )
    return canonical


# ── Composition ──────────────────────────────────────────────────────────

@dataclass
class Composition:
    """Resolved boot tree — the thing ``--dump-config`` prints and patches target."""

    profile: str
    runtime: RuntimeConfig
    layers: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        """Serializable view of the resolved composition (api_key redacted)."""
        d = self.runtime.as_dict()
        if d.get("api_key"):
            d["api_key"] = "***REDACTED***"
        return {
            "profile": self.profile,
            "layers": self.layers,
            "runtime": d,
        }

    def dump(self) -> str:
        """JSON text of the resolved composition — what --dump-config prints."""
        return json.dumps(self.as_dict(), indent=2)


def build_composition(
    config: Config | None = None,
    *,
    profile: str | None = None,
    home_patch: dict | None = None,
    overlay_patch: dict | None = None,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Composition:
    """Compose the boot tree: base → profile patch → home patch → overlay.

    Args:
        config: Loaded Config (single loader). Defaults to ``Config()``.
        profile: Named profile (``default``/``tui``/``server``/``headless``).
        home_patch: Rows from the user's micron.yaml ``profiles:`` section.
        overlay_patch: Rows from a ``--patch`` overlay file (highest layer).
        provider/model/temperature/max_tokens: CLI flag overrides, applied
            as part of the base composition (before profile/home/overlay).

    Returns:
        A ``Composition`` — pass it to :func:`boot` to wire agent+sessions.
    """
    config = config or Config()
    canonical = canonical_profile(profile)

    # Base composition: Config.runtime() hoists the provider row; CLI flag
    # overrides fold in here so every later layer sees them.
    base: dict = {}
    if provider:
        base["provider"] = provider
    if model:
        base["model"] = model
    if temperature is not None:
        base["temperature"] = temperature
    if max_tokens is not None:
        base["max_tokens"] = max_tokens

    rt = config.runtime(
        provider_override=provider,
        model_override=model,
    )
    if temperature is not None:
        rt = rt.replace(temperature=temperature)
    if max_tokens is not None:
        rt = rt.replace(max_tokens=max_tokens)

    layers: list[dict] = [{"id": "base", "patch": base}]

    # Layer 1: profile patch
    profile_patch = dict(PROFILE_PATCHES[canonical])
    rt = apply_patch_layer(rt, profile_patch)
    layers.append({"id": f"profile:{canonical}", "patch": profile_patch})

    # Layer 2: home patch (user's micron.yaml profiles section)
    home = dict(home_patch or {})
    rt = apply_patch_layer(rt, home)
    layers.append({"id": "home", "patch": home})

    # Layer 3: --patch overlay file
    overlay = dict(overlay_patch or {})
    rt = apply_patch_layer(rt, overlay)
    layers.append({"id": "overlay", "patch": overlay})

    return Composition(profile=canonical, runtime=rt, layers=layers)


# ── Boot ─────────────────────────────────────────────────────────────────

@dataclass
class Boot:
    """Composed runtime: agent + sessions + limiter/auth, one wiring for all profiles."""

    composition: Composition
    agent: object
    sessions: object | None
    limiter: object
    auth: object
    server_runtime: object  # micron.server_runtime.ServerRuntime


def boot(
    composition: Composition,
    *,
    config: Config | None = None,
    sessions: bool = True,
) -> Boot:
    """Wire agent + sessions + limiter/auth from a Composition.

    Single boot path: delegates to ``ServerRuntime`` (the deep module from
    ADR 0007) so CLI one-shot, TUI, server, and headless all share the same
    wiring. ``sessions=False`` (headless) skips the session logger entirely.
    """
    from micron.server_runtime import ServerRuntime

    rt = ServerRuntime(
        composition.runtime,
        sessions=None if sessions else False,
    )
    return Boot(
        composition=composition,
        agent=rt.agent,
        sessions=rt.sessions,
        limiter=rt.limiter,
        auth=rt.auth,
        server_runtime=rt,
    )
