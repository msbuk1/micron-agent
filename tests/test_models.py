"""Tests for MicronAgent.set_backend and the /models slash command."""
from __future__ import annotations

import pytest


# ──────────────────────────────────────────────────────────────────────
# set_backend
# ──────────────────────────────────────────────────────────────────────


class _FakeLLM:
    """Minimal stand-in for an LLM backend."""

    def __init__(self, *, available: bool = True, unload_called: list | None = None):
        self._available = available
        self.unload_called = unload_called if unload_called is not None else []

    def is_available(self) -> bool:
        return self._available

    def unload(self) -> None:
        self.unload_called.append(True)

    def stream_chat(self, *a, **kw):
        return iter([])


class _CountingLLM(_FakeLLM):
    """Records constructor calls so we can verify create_backend is invoked."""

    instances: list = []

    def __init__(self, *, available: bool = True, unload_called=None, **kwargs):
        type(self).instances.append(kwargs)
        super().__init__(available=available, unload_called=unload_called)


def _make_agent(provider: str = "lmstudio", model: str = "old-model", available: bool = True):
    """Build a minimal MicronAgent for set_backend testing.

    Avoids touching the filesystem beyond an isolated temp dir.
    """
    import tempfile
    from pathlib import Path
    from micron.agent import MicronAgent, AgentConfig

    with tempfile.TemporaryDirectory() as td:
        cfg = AgentConfig(
            context_dir=str(td),
            provider=provider,
            model=model,
            llm_kwargs={
                "backend": _FakeLLM(available=available),
                "base_url": "http://localhost:1234/v1",
                "api_key": "no_key",
            },
        )
        agent = MicronAgent(cfg)
    return agent


def test_set_backend_unloads_old():
    """Old backend's unload() is called when swapping."""
    unload_log: list = []
    import tempfile
    from pathlib import Path
    from micron.agent import MicronAgent, AgentConfig

    with tempfile.TemporaryDirectory() as td:
        old = _FakeLLM(unload_called=unload_log)
        cfg = AgentConfig(
            context_dir=str(td),
            provider="lmstudio",
            model="old",
            llm_kwargs={"backend": old, "base_url": "http://localhost:1234/v1", "api_key": "no_key"},
        )
        agent = MicronAgent(cfg)

    # Now swap to a different fake (we bypass create_backend by using llm_kwargs).
    new_llm = _FakeLLM(available=True)
    # set_backend calls create_backend internally; to keep this test
    # hermetic we monkeypatch the factory in the agent module.
    import micron.agent as agent_mod

    agent_mod.create_backend = lambda provider, model, **kw: new_llm
    try:
        agent.set_backend("ollama", "llama3", base_url="http://localhost:11434")
    finally:
        # restore (not strictly necessary in a temp test, but be safe)
        pass

    assert unload_log == [True], "old backend's unload() was not called"
    assert agent.provider == "ollama"
    assert agent.model == "llama3"
    assert agent.llm is new_llm
    assert agent.config.provider == "ollama"
    assert agent.config.model == "llama3"


def test_set_backend_rolls_back_when_unavailable():
    """If is_available() returns False, agent keeps the old backend."""
    import tempfile
    from micron.agent import MicronAgent, AgentConfig
    import micron.agent as agent_mod

    with tempfile.TemporaryDirectory() as td:
        old = _FakeLLM(available=True)
        cfg = AgentConfig(
            context_dir=str(td),
            provider="lmstudio",
            model="old",
            llm_kwargs={"backend": old, "base_url": "http://localhost:1234/v1", "api_key": "no_key"},
        )
        agent = MicronAgent(cfg)

    new_llm = _FakeLLM(available=False)
    agent_mod.create_backend = lambda provider, model, **kw: new_llm

    with pytest.raises(RuntimeError, match="not available"):
        agent.set_backend("ollama", "llama3", base_url="http://localhost:11434")

    # Old backend preserved
    assert agent.provider == "lmstudio"
    assert agent.model == "old"
    assert agent.llm is old


def test_set_backend_placeholder_key_hint():
    """A placeholder key in the failure message points at micron.yaml."""
    from micron.agent import _availability_hint

    class Backend:
        api_key = "<your-openrouter-api-key>"

    assert "placeholder" in _availability_hint(Backend(), "openrouter")
    assert _availability_hint(type("B", (), {"api_key": "sk-real"})(), "openrouter") == ""
    assert "missing API key" in _availability_hint(type("B", (), {"api_key": ""})(), "openai")


def test_set_backend_updates_use_text_tool_format():
    """Switching to llamacpp enables text-tool parsing."""
    import tempfile
    from micron.agent import MicronAgent, AgentConfig
    import micron.agent as agent_mod

    with tempfile.TemporaryDirectory() as td:
        old = _FakeLLM(available=True)
        cfg = AgentConfig(
            context_dir=str(td),
            provider="lmstudio",
            model="old",
            llm_kwargs={"backend": old, "base_url": "http://localhost:1234/v1", "api_key": "no_key"},
        )
        agent = MicronAgent(cfg)
    assert agent.use_text_tool_format is False

    new_llm = _FakeLLM(available=True)
    agent_mod.create_backend = lambda provider, model, **kw: new_llm
    agent.set_backend("llamacpp", "model.gguf", n_threads=8)

    assert agent.use_text_tool_format is True
    assert agent.prompt_builder.use_text_tool_format is True


def test_set_backend_handles_missing_unload():
    """Backends without unload() don't break the swap."""
    import tempfile
    from micron.agent import MicronAgent, AgentConfig
    import micron.agent as agent_mod

    class NoUnloadLLM(_FakeLLM):
        def __init__(self, **kwargs):
            super().__init__(available=True)
            # no unload method

    with tempfile.TemporaryDirectory() as td:
        old = NoUnloadLLM()
        cfg = AgentConfig(
            context_dir=str(td),
            provider="lmstudio",
            model="old",
            llm_kwargs={"backend": old, "base_url": "http://localhost:1234/v1", "api_key": "no_key"},
        )
        agent = MicronAgent(cfg)

    new_llm = _FakeLLM(available=True)
    agent_mod.create_backend = lambda provider, model, **kw: new_llm
    agent.set_backend("ollama", "llama3", base_url="http://localhost:11434")

    assert agent.provider == "ollama"
    assert agent.llm is new_llm


# ──────────────────────────────────────────────────────────────────────
# /models command (dispatcher)
# ──────────────────────────────────────────────────────────────────────


class TestModelsCommand:
    def _make_dispatcher(self, providers: dict | None = None):
        """Build a dispatcher whose Config + agent are wired to fakes."""
        from micron.tui.commands import CommandDispatcher

        class FakeApp:
            conversation_history: list = []

        class FakeAgent:
            class FakeLLM:
                def is_available(self):
                    return True

            llm = FakeLLM()
            provider = "lmstudio"
            model = "active-model"

        app = FakeApp()
        agent = FakeAgent()
        logger = object()
        d = CommandDispatcher(app, agent, logger, {})

        # Patch load_config + agent.set_backend.
        from micron.config import load_config as _real

        class FakeCfg:
            def __init__(self, providers):
                self._p = providers

            def get(self, key, default=None):
                if key == "providers":
                    return self._p
                return default

        d._fake_cfg = FakeCfg(providers or {})
        d._fake_providers = providers or {}
        d._switch_log: list = []

        # Keep the config-fallback path hermetic: no live API calls.
        d._fetch_provider_models = lambda prov_name, prov_cfg: []

        def fake_load_config():
            return d._fake_cfg

        # Patch in the module the dispatcher uses.
        import micron.tui.commands as cmd_mod
        d._orig_load_config = cmd_mod.__dict__.get("load_config", None)

        def _patched_load_config():
            return fake_load_config()

        # _models/_switch_model call load_config from inside the
        # function via `from micron.config import load_config`. Patch
        # micron.config instead.
        import micron.config as cfg_mod
        d._orig_cfg_load = cfg_mod.load_config
        cfg_mod.load_config = _patched_load_config

        def fake_set_backend(provider, model, **kwargs):
            d._switch_log.append((provider, model, kwargs))
            agent.provider = provider
            agent.model = model

        agent.set_backend = fake_set_backend

        return d

    def _teardown(self, d):
        import micron.config as cfg_mod
        cfg_mod.load_config = d._orig_cfg_load

    def test_models_lists_all_with_active_marker(self):
        d = self._make_dispatcher({
            "lmstudio": {"model": "active-model", "base_url": "http://localhost:1234/v1"},
            "ollama": {"model": "llama3", "base_url": "http://localhost:11434"},
        })
        try:
            result = d.handle("/models")
        finally:
            self._teardown(d)
        assert "Available models:" in result.text
        assert "lmstudio" in result.text
        assert "active-model" in result.text
        assert "← active" in result.text
        assert "ollama" in result.text
        assert "llama3" in result.text
        assert result.open_model_picker is True
        assert ("ollama", "llama3", {}) in result.model_entries

    def test_models_filters_by_provider(self):
        d = self._make_dispatcher({
            "lmstudio": {"model": "m1", "base_url": "http://localhost:1234/v1"},
            "ollama": {"model": "llama3", "base_url": "http://localhost:11434"},
        })
        try:
            result = d.handle("/models ollama")
        finally:
            self._teardown(d)
        assert "ollama" in result.text
        assert "llama3" in result.text
        assert "lmstudio" not in result.text
        assert result.open_model_picker is True
        assert result.model_entries == [("ollama", "llama3", {})]

    def test_models_unknown_provider(self):
        d = self._make_dispatcher({"lmstudio": {"model": "m1"}})
        try:
            result = d.handle("/models nope")
        finally:
            self._teardown(d)
        assert "Unknown provider" in result.text
        assert "nope" in result.text

    def test_models_switch_calls_set_backend(self):
        d = self._make_dispatcher({
            "lmstudio": {"model": "m1", "base_url": "http://localhost:1234/v1", "api_key": "k"},
            "ollama": {"model": "llama3", "base_url": "http://localhost:11434"},
        })
        try:
            result = d.handle("/models ollama llama3")
        finally:
            self._teardown(d)
        assert "Switched" in result.text
        assert d._switch_log == [("ollama", "llama3", {"base_url": "http://localhost:11434"})]

    def test_models_numeric_select_after_list(self):
        d = self._make_dispatcher({
            "lmstudio": {"model": "m1"},
            "ollama": {"model": "llama3"},
        })
        try:
            d.handle("/models")  # populate _last_models
            result = d.handle("/models 2")  # pick ollama
        finally:
            self._teardown(d)
        assert d._switch_log[0][0] == "ollama"
        assert "Switched" in result.text

    def test_models_numeric_without_prior_list(self):
        d = self._make_dispatcher({"lmstudio": {"model": "m1"}})
        try:
            result = d.handle("/models 1")
        finally:
            self._teardown(d)
        assert "No model list yet" in result.text

    def test_models_switch_unknown_provider(self):
        d = self._make_dispatcher({"lmstudio": {"model": "m1"}})
        try:
            result = d.handle("/models nope x")
        finally:
            self._teardown(d)
        assert "Unknown provider" in result.text
        assert d._switch_log == []

    def test_models_switch_failure_keeps_state(self):
        d = self._make_dispatcher({"lmstudio": {"model": "m1"}})

        def boom(*a, **kw):
            raise RuntimeError("offline")

        d.agent.set_backend = boom
        try:
            result = d.handle("/models lmstudio m1")
        finally:
            self._teardown(d)
        assert "Failed to switch" in result.text
        assert "offline" in result.text

    def test_models_supports_multiple_models_field(self):
        d = self._make_dispatcher({
            "lmstudio": {
                "models": ["gemma", "ministral"],
                "base_url": "http://localhost:1234/v1",
            },
            "ollama": {"model": "llama3", "base_url": "http://localhost:11434"},
        })
        try:
            result = d.handle("/models")
        finally:
            self._teardown(d)
        assert "gemma" in result.text
        assert "ministral" in result.text
        assert "llama3" in result.text

    def test_models_registered_in_registry(self):
        d = self._make_dispatcher({"lmstudio": {"model": "m1"}})
        assert d.registry.get("models") is not None
        self._teardown(d)

    def test_models_appears_in_help(self):
        d = self._make_dispatcher({"lmstudio": {"model": "m1"}})
        try:
            result = d.handle("/help")
        finally:
            self._teardown(d)
        assert "/models" in result.text


# ──────────────────────────────────────────────────────────────────────
# live model discovery
# ──────────────────────────────────────────────────────────────────────


class _MockResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TestProviderModelDiscovery:
    def _dispatcher(self, providers):
        from micron.tui.commands import CommandDispatcher

        class FakeApp:
            conversation_history: list = []

        class FakeAgent:
            provider = "lmstudio"
            model = "active-model"
            llm = object()

        d = CommandDispatcher(FakeApp(), FakeAgent(), object(), {})
        d._fake_providers = providers
        return d

    def test_ollama_fetches_from_api_tags(self, monkeypatch):
        import requests as _requests

        d = self._dispatcher({"ollama": {"base_url": "http://localhost:11434"}})
        monkeypatch.setattr(
            _requests,
            "get",
            lambda url, **kw: (
                _MockResponse({
                    "models": [
                        {"name": "llama3", "parameter_size": "8B",
                         "quantization_level": "Q4_K_M"},
                        {"name": "qwen2.5", "parameter_size": "7B"},
                    ]
                })
                if url.endswith("/api/tags")
                else _MockResponse({})
            ),
        )
        assert d._fetch_provider_models("ollama", {"base_url": "http://localhost:11434"}) == [
            {
                "name": "llama3",
                "meta": {"parameter_size": "8B", "quantization_level": "Q4_K_M"},
            },
            {
                "name": "qwen2.5",
                "meta": {"parameter_size": "7B"},
            },
        ]

    def test_openai_compatible_fetches_from_models(self, monkeypatch):
        import requests as _requests

        d = self._dispatcher({"lmstudio": {"base_url": "http://localhost:1234/v1"}})
        monkeypatch.setattr(
            _requests,
            "get",
            lambda url, **kw: (
                _MockResponse({
                    "data": [
                        {
                            "id": "gemma",
                            "pricing": {"prompt": "4e-06", "completion": "1.6e-05"},
                            "context_length": 128000,
                        },
                        {"id": "ministral", "context_length": 256000},
                    ]
                })
                if url.endswith("/models")
                else _MockResponse({})
            ),
        )
        prov_cfg = {"base_url": "http://localhost:1234/v1", "api_key": "no_key"}
        assert d._fetch_provider_models("lmstudio", prov_cfg) == [
            {
                "name": "gemma",
                "meta": {
                    "pricing": {"prompt": "4e-06", "completion": "1.6e-05"},
                    "context_length": 128000,
                },
            },
            {
                "name": "ministral",
                "meta": {"context_length": 256000},
            },
        ]

    def test_unknown_provider_returns_empty(self):
        d = self._dispatcher({})
        assert d._fetch_provider_models("nope", {"base_url": "http://x"}) == []

    def test_missing_base_url_returns_empty(self):
        d = self._dispatcher({})
        assert d._fetch_provider_models("ollama", {}) == []

    def test_fetch_error_falls_back_to_config(self, monkeypatch):
        import requests as _requests

        d = self._dispatcher({"ollama": {"base_url": "http://localhost:11434"}})
        monkeypatch.setattr(
            _requests,
            "get",
            lambda url, **kw: _MockResponse({}, status_code=500),
        )
        # After the real method (unpatched) fails, config fallback kicks in.
        from unittest.mock import patch

        class FakeCfg:
            def get(self, key, default=None):
                if key == "providers":
                    return {"ollama": {"model": "llama3"}}
                return default

        with patch("micron.config.load_config", return_value=FakeCfg()):
            assert d._all_model_entries() == [("ollama", "llama3", {})]

    def test_format_model_meta_renders_cost_and_context(self):
        from micron.tui.commands import _format_price

        assert _format_price("4e-06") == "4"
        assert _format_price("7.5e-08") == "0.075"
        assert _format_price("3e-07") == "0.3"
        assert _format_price("0") == "0"
        assert _format_price(1.6e-05) == "16"
        assert _format_price("not-a-number") == "not-a-number"

        d = self._dispatcher({})
        meta = {
            "pricing": {"prompt": "7.5e-08", "completion": "3e-07"},
            "context_length": 128000,
        }
        detail = d._format_model_meta(meta)
        assert "$0.075/$0.3 · per M tok" in detail
        assert "128k ctx" in detail

    def test_format_model_meta_ollama(self):
        d = self._dispatcher({})
        detail = d._format_model_meta(
            {"parameter_size": "8B", "quantization_level": "Q4_K_M"}
        )
        assert "8B" in detail
        assert "Q4_K_M" in detail

    def test_format_model_meta_empty(self):
        d = self._dispatcher({})
        assert d._format_model_meta({}) == ""


# ──────────────────────────────────────────────────────────────────────
# OpenAICompatibleBackend credential validation
# ──────────────────────────────────────────────────────────────────────


class TestOpenAICompatibleAvailability:
    def _backend(self, **kw):
        from micron.llm import OpenAICompatibleBackend
        return OpenAICompatibleBackend(**kw)

    def test_placeholder_key_is_unavailable(self):
        b = self._backend(api_key="<your-openrouter-api-key>")
        assert b.is_available() is False

    def test_empty_key_is_unavailable(self):
        b = self._backend(api_key="")
        assert b.is_available() is False

    def test_openrouter_probes_key_endpoint(self, monkeypatch):
        import requests as _requests

        b = self._backend(api_key="sk-real")
        calls = []
        monkeypatch.setattr(
            _requests,
            "get",
            lambda url, **kw: (calls.append(url) or _MockResponse({})),
        )
        assert b.is_available() is True
        assert calls and calls[0].endswith("/key")

    def test_openrouter_bad_key_is_unavailable(self, monkeypatch):
        import requests as _requests

        b = self._backend(api_key="sk-bad")
        monkeypatch.setattr(
            _requests,
            "get",
            lambda url, **kw: _MockResponse({}, status_code=401),
        )
        assert b.is_available() is False

    def test_non_openrouter_probes_models_endpoint(self, monkeypatch):
        import requests as _requests

        b = self._backend(api_key="no_key", base_url="http://localhost:1234/v1")
        calls = []
        monkeypatch.setattr(
            _requests,
            "get",
            lambda url, **kw: (calls.append(url) or _MockResponse({"data": []})),
        )
        assert b.is_available() is True
        assert calls and calls[0].endswith("/models")


# ──────────────────────────────────────────────────────────────────────
# auth.yaml secrets merge
# ──────────────────────────────────────────────────────────────────────


def test_deep_merge_overlays_nested_dicts():
    from micron.config import _deep_merge

    base = {"providers": {"openrouter": {"api_key": "<placeholder>", "base_url": "https://or"}}}
    overlay = {"providers": {"openrouter": {"api_key": "sk-real"}}}
    merged = _deep_merge(base, overlay)
    assert merged["providers"]["openrouter"]["api_key"] == "sk-real"
    assert merged["providers"]["openrouter"]["base_url"] == "https://or"


def test_deep_merge_scalar_replacement():
    from micron.config import _deep_merge

    merged = _deep_merge({"a": {"b": 1}}, {"a": {"b": 2}})
    assert merged["a"]["b"] == 2


def test_config_loads_auth_yaml(tmp_path, monkeypatch):
    """Config merges a sibling auth.yaml over micron.yaml."""
    import yaml
    from micron.config import Config

    (tmp_path / "micron.yaml").write_text(yaml.safe_dump({
        "providers": {"openrouter": {"api_key": "<placeholder>", "base_url": "https://or"}},
    }))
    (tmp_path / "auth.yaml").write_text(yaml.safe_dump({
        "providers": {"openrouter": {"api_key": "sk-real"}},
    }))
    cfg = Config(config_path=str(tmp_path / "micron.yaml"))
    assert cfg.get("providers.openrouter.api_key") == "sk-real"
    assert cfg.get("providers.openrouter.base_url") == "https://or"


def test_config_without_auth_yaml_uses_placeholders(tmp_path):
    import yaml
    from micron.config import Config

    (tmp_path / "micron.yaml").write_text(yaml.safe_dump({
        "providers": {"openrouter": {"api_key": "<placeholder>"}},
    }))
    cfg = Config(config_path=str(tmp_path / "micron.yaml"))
    assert cfg.get("providers.openrouter.api_key") == "<placeholder>"
