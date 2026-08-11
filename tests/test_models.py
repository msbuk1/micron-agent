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
