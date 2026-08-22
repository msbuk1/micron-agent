"""ModelCatalog — deep module owning model discovery + formatting + switch.

Single owner for: live fetch (/api/tags vs /models), fallback chain (models list → model string),
price/meta formatting, and switch validation. Dispatcher becomes thin adapter.
Seam: ModelCatalog(config, *, source) — source is HTTP port (real vs FakeSource).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


def _format_price(raw) -> str:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    per_m = value * 1e6
    if per_m == 0:
        return "0"
    text = f"{per_m:.6f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True, slots=True)
class ModelEntry:
    provider: str
    name: str
    meta: dict

    @property
    def price(self) -> str:
        pricing = self.meta.get("pricing")
        if isinstance(pricing, dict) and pricing.get("prompt") is not None:
            prompt = _format_price(pricing.get("prompt"))
            completion = _format_price(pricing.get("completion"))
            return f"${prompt}/${completion}"
        return ""

    @property
    def rest(self) -> str:
        parts: list[str] = []
        pricing = self.meta.get("pricing")
        if isinstance(pricing, dict) and pricing.get("prompt") is not None:
            parts.append("per M tok")
        ctx = self.meta.get("context_length")
        if isinstance(ctx, int) and ctx:
            if ctx >= 1_000_000 and ctx % 1_000_000 == 0:
                parts.append(f"{ctx // 1_000_000}m ctx")
            elif ctx % 1000 == 0:
                parts.append(f"{ctx // 1000}k ctx")
            else:
                parts.append(f"{ctx} ctx")
        params = self.meta.get("parameter_size")
        if params:
            parts.append(str(params))
        quant = self.meta.get("quantization_level")
        if quant:
            parts.append(str(quant))
        return " · ".join(parts)

    @property
    def detail(self) -> str:
        price, rest = self.price, self.rest
        return " · ".join(p for p in (price, rest) if p)


class ModelSource(Protocol):
    def fetch(self, provider: str, cfg: dict) -> list[dict]: ...


class HttpModelSource:
    def fetch(self, provider: str, cfg: dict) -> list[dict]:
        base_url = cfg.get("base_url")
        if not base_url:
            return []
        try:
            import requests

            if provider == "ollama":
                resp = requests.get(f"{base_url}/api/tags", timeout=2)
                resp.raise_for_status()
                return [
                    {
                        "name": m.get("name", ""),
                        "meta": {k: m.get(k) for k in ("parameter_size", "quantization_level", "size") if m.get(k) is not None},
                    }
                    for m in resp.json().get("models", [])
                    if m.get("name")
                ]
            headers: dict[str, str] = {}
            api_key = cfg.get("api_key")
            if api_key and api_key != "no_key":
                headers["Authorization"] = f"Bearer {api_key}"
            resp = requests.get(f"{base_url}/models", headers=headers, timeout=2)
            resp.raise_for_status()
            return [
                {
                    "name": m.get("id", ""),
                    "meta": {k: m.get(k) for k in ("pricing", "context_length", "description") if m.get(k) is not None},
                }
                for m in resp.json().get("data", [])
                if m.get("id")
            ]
        except Exception:
            return []


class ModelCatalog:
    def __init__(self, config=None, *, source: ModelSource | None = None):
        # config may be Config instance, dict, or None (load)
        if config is None:
            try:
                from micron.config import load_config

                cfg = load_config()
                providers = cfg.get("providers", {}) if cfg else {}
            except Exception:
                providers = {}
            self._providers = providers
        elif hasattr(config, "get"):
            # Config-like
            try:
                self._providers = config.get("providers", {}) if config else {}
            except Exception:
                self._providers = {}
        else:
            # dict
            self._providers = dict(config.get("providers", {})) if isinstance(config, dict) else {}
            if not self._providers and isinstance(config, dict):
                self._providers = dict(config)
        self._source = source or HttpModelSource()

    def list(self, provider: str | None = None) -> list[ModelEntry]:
        entries: list[ModelEntry] = []
        providers = self._providers
        for prov_name, prov_cfg in providers.items():
            if provider is not None and prov_name != provider:
                continue
            live = self._source.fetch(prov_name, prov_cfg)
            if live:
                for m in live:
                    entries.append(ModelEntry(provider=prov_name, name=m["name"], meta=m.get("meta", {})))
                continue
            models = prov_cfg.get("models")
            if isinstance(models, list) and models:
                for m in models:
                    entries.append(ModelEntry(provider=prov_name, name=m, meta={}))
            elif prov_cfg.get("model"):
                entries.append(ModelEntry(provider=prov_name, name=prov_cfg["model"], meta={}))
        return entries

    def get(self, provider: str, model: str) -> ModelEntry | None:
        for e in self.list(provider=provider):
            if e.name == model:
                return e
        return None

    def text(self, entries: list[ModelEntry] | None = None, *, active: tuple[str, str] | None = None) -> str:
        if entries is None:
            entries = self.list()
        rows = [(e.provider, e.name, e.price, e.rest) for e in entries]
        lines = ["Available models:"]
        if not rows:
            lines.append("  (none configured)")
            lines.append("")
            lines.append("Use: /models <provider> [<model>]")
            return "\n".join(lines)
        model_w = max(len(m) for _, m, _, _ in rows)
        price_w = max(len(p) for _, _, p, _ in rows)
        for prov, model, price, rest in rows:
            marker = "  ← active" if active and (prov, model) == active else ""
            detail = " ".join(part for part in (f"{price:>{price_w}}", rest) if part)
            lines.append(f"  {prov:<11} {model:<{model_w}}  [{detail}]{marker}")
        lines.append("")
        lines.append("Use: /models <provider> [<model>]")
        return "\n".join(lines)

    def switch(self, agent, provider: str, model: str, *, persist: bool = True) -> str:
        try:
            from micron.config import load_config

            cfg = load_config()
            prov_cfg = (cfg.get("providers", {}) or {}).get(provider, {})
        except Exception:
            cfg = None
            prov_cfg = self._providers.get(provider, {})
        if not prov_cfg:
            return f"Unknown provider: {provider}."
        kwargs = {k: v for k, v in prov_cfg.items() if k not in ("model", "models")}
        try:
            agent.set_backend(provider, model, **kwargs)
        except Exception as e:
            return f"Failed to switch to {provider}/{model}: {e}"
        if persist and cfg is not None and getattr(cfg, "config_path", None):
            try:
                import yaml

                path = cfg.config_path
                data = {}
                if path.exists():
                    data = yaml.safe_load(path.read_text()) or {}
                data["default_provider"] = provider
                if "providers" not in data:
                    data["providers"] = {}
                if provider not in data["providers"]:
                    data["providers"][provider] = {}
                data["providers"][provider]["model"] = model
                path.write_text(yaml.safe_dump(data, sort_keys=False))
            except Exception:
                pass
        # Update in-memory cache so next list shows new active without reload
        if provider in self._providers:
            self._providers[provider] = dict(self._providers[provider])
            self._providers[provider]["model"] = model
        return f"Switched to {provider}/{model}.\nUse /models to confirm."

    @property
    def providers(self) -> list[str]:
        return list(self._providers.keys())

    @property
    def size(self) -> int:
        return len(self.list())
