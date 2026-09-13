"""Tests for profiles-as-composition + --dump-config (issue #16).

Covers:
- ordered patch layers apply deterministically (base → profile → home → overlay)
- later layers replace whole rows by id or insert new rows
- --dump-config output shape (resolved composition, redaction, layer ids)
- single boot path: boot() wires agent+sessions+limiter/auth for every profile
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from micron.config import RuntimeConfig
from micron.llm import LLMResponse
from micron.profiles import (
    Composition,
    apply_patch_layer,
    boot,
    build_composition,
    canonical_profile,
)


class FakeBackend:
    """Fake LLM backend — injected so boot() never builds a real one."""

    def is_available(self) -> bool:
        return True

    def stream_chat(self, messages, tools=None, temperature=0.1, max_tokens=2048):
        yield LLMResponse(type="text", content="ok")
        yield LLMResponse(type="done")


def _fake_rt(tmp_path, **overrides) -> RuntimeConfig:
    return RuntimeConfig.fake(tmp_path, **overrides)


# ── apply_patch_layer ────────────────────────────────────────────────────


class TestApplyPatchLayer:
    def test_scalar_row_replaced(self, tmp_path):
        rt = _fake_rt(tmp_path, temperature=0.1)
        out = apply_patch_layer(rt, {"temperature": 0.9})
        assert out.temperature == 0.9
        # frozen dataclass — original untouched
        assert rt.temperature == 0.1

    def test_new_row_inserted(self, tmp_path):
        rt = _fake_rt(tmp_path)
        out = apply_patch_layer(rt, {"port": 9999})
        assert out.port == 9999

    def test_unknown_row_raises(self, tmp_path):
        rt = _fake_rt(tmp_path)
        with pytest.raises(ValueError, match="no_such_row"):
            apply_patch_layer(rt, {"no_such_row": 1})

    def test_empty_patch_is_identity(self, tmp_path):
        rt = _fake_rt(tmp_path)
        out = apply_patch_layer(rt, {})
        assert out == rt


# ── canonical_profile ────────────────────────────────────────────────────


class TestCanonicalProfile:
    def test_none_is_default(self):
        assert canonical_profile(None) == "default"

    def test_alias_one_shot(self):
        assert canonical_profile("one-shot") == "default"

    def test_alias_interactive(self):
        assert canonical_profile("interactive") == "tui"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown profile"):
            canonical_profile("bogus")

    def test_all_named_profiles_exist(self):
        for name in ("default", "one-shot", "tui", "interactive", "server", "headless"):
            assert canonical_profile(name) in ("default", "tui", "server", "headless")


# ── build_composition: layer ordering ────────────────────────────────────


class TestLayerOrdering:
    def test_four_layers_recorded_in_order(self, tmp_path):
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path)
        comp = build_composition(
            cfg,
            profile="tui",
            home_patch={"temperature": 0.5},
            overlay_patch={"temperature": 0.7},
        )
        ids = [layer["id"] for layer in comp.layers]
        assert ids == ["base", "profile:tui", "home", "overlay"]

    def test_later_layer_wins(self, tmp_path):
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path, temperature=0.1)
        comp = build_composition(
            cfg,
            home_patch={"temperature": 0.5},
            overlay_patch={"temperature": 0.7},
        )
        assert comp.runtime.temperature == 0.7

    def test_overlay_inserts_row_home_did_not_have(self, tmp_path):
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path)
        comp = build_composition(cfg, overlay_patch={"port": 7777})
        assert comp.runtime.port == 7777
        assert comp.layers[3]["patch"] == {"port": 7777}

    def test_home_patch_without_overlay(self, tmp_path):
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path)
        comp = build_composition(cfg, home_patch={"max_tokens": 42})
        assert comp.runtime.max_tokens == 42
        assert comp.layers[2]["patch"] == {"max_tokens": 42}
        assert comp.layers[3]["patch"] == {}

    def test_cli_flags_fold_into_base_layer(self, tmp_path):
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path, temperature=0.1)
        comp = build_composition(cfg, temperature=0.3, max_tokens=500)
        assert comp.layers[0]["patch"] == {"temperature": 0.3, "max_tokens": 500}
        assert comp.runtime.temperature == 0.3
        assert comp.runtime.max_tokens == 500

    def test_profile_patch_applied_over_base(self, tmp_path):
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path)
        comp = build_composition(cfg, profile="headless")
        assert comp.profile == "headless"
        assert comp.layers[1]["id"] == "profile:headless"

    def test_deterministic_same_inputs_same_output(self, tmp_path):
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path)
        a = build_composition(cfg, home_patch={"port": 1}, overlay_patch={"port": 2})
        b = build_composition(cfg, home_patch={"port": 1}, overlay_patch={"port": 2})
        assert a.as_dict() == b.as_dict()


# ── Composition dump ─────────────────────────────────────────────────────


class TestDumpConfig:
    def test_dump_is_valid_json_with_expected_shape(self, tmp_path):
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path)
        comp = build_composition(cfg, profile="server")
        parsed = json.loads(comp.dump())
        assert parsed["profile"] == "server"
        assert [l["id"] for l in parsed["layers"]] == [
            "base", "profile:server", "home", "overlay",
        ]
        assert parsed["runtime"]["provider"] == "fake"

    def test_dump_redacts_api_key(self, tmp_path):
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path, api_key="sk-secret")
        comp = build_composition(cfg)
        parsed = json.loads(comp.dump())
        assert parsed["runtime"]["api_key"] == "***REDACTED***"
        assert "sk-secret" not in comp.dump()

    def test_dump_reflects_patch_layers(self, tmp_path):
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path, port=8000)
        comp = build_composition(cfg, overlay_patch={"port": 9001})
        parsed = json.loads(comp.dump())
        assert parsed["runtime"]["port"] == 9001


# ── boot: single wiring for every profile ────────────────────────────────


class TestBoot:
    def _comp(self, tmp_path, profile=None, **kw) -> Composition:
        cfg = MagicMock()
        cfg.runtime.return_value = _fake_rt(tmp_path, **kw)
        return build_composition(cfg, profile=profile)

    def _boot(self, tmp_path, profile=None, sessions=True, **kw):
        comp = self._comp(tmp_path, profile=profile, **kw)
        with patch("micron.agent.create_backend", return_value=FakeBackend()):
            return boot(comp, sessions=sessions)

    def test_boot_wires_agent_sessions_gates(self, tmp_path):
        b = self._boot(tmp_path)
        assert b.agent is not None
        assert b.sessions is not None
        assert b.limiter is not None
        assert b.auth is not None

    def test_boot_headless_disables_sessions(self, tmp_path):
        b = self._boot(tmp_path, profile="headless", sessions=False)
        assert b.agent is not None
        assert b.sessions is None

    def test_boot_same_composition_same_wiring_shape(self, tmp_path):
        """Every profile boots through the same ServerRuntime wiring."""
        for profile in (None, "tui", "server"):
            b = self._boot(tmp_path, profile=profile)
            assert b.agent is not None
            assert b.server_runtime.runtime.provider == "fake"

    def test_boot_agent_uses_composition_runtime(self, tmp_path):
        b = self._boot(tmp_path, temperature=0.42, max_tokens=1234)
        assert b.agent.config.temperature == 0.42
        assert b.agent.config.max_tokens == 1234


# ── CLI --dump-config ────────────────────────────────────────────────────


class TestCliDumpConfig:
    def test_dump_config_flag_prints_and_exits(self, tmp_path, capsys):
        from micron.__main__ import main

        with patch("micron.__main__.Config") as MockConfig:
            MockConfig.return_value.runtime.return_value = _fake_rt(tmp_path)
            MockConfig.return_value.get.return_value = None
            with patch("sys.argv", ["micron", "--dump-config"]):
                main()

        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["profile"] == "default"
        assert [l["id"] for l in parsed["layers"]] == [
            "base", "profile:default", "home", "overlay",
        ]

    def test_dump_config_with_patch_overlay(self, tmp_path, capsys):
        from micron.__main__ import main

        patch_file = tmp_path / "overlay.json"
        patch_file.write_text(json.dumps({"port": 9119}))

        with patch("micron.__main__.Config") as MockConfig:
            MockConfig.return_value.runtime.return_value = _fake_rt(tmp_path)
            MockConfig.return_value.get.return_value = None
            with patch("sys.argv", ["micron", "--dump-config", "--patch", str(patch_file)]):
                main()

        parsed = json.loads(capsys.readouterr().out)
        assert parsed["runtime"]["port"] == 9119
        assert parsed["layers"][3]["patch"] == {"port": 9119}

    def test_dump_config_does_not_boot_agent(self, tmp_path, capsys):
        from micron.__main__ import main

        with patch("micron.__main__.Config") as MockConfig, \
             patch("micron.__main__.boot") as mock_boot:
            MockConfig.return_value.runtime.return_value = _fake_rt(tmp_path)
            MockConfig.return_value.get.return_value = None
            with patch("sys.argv", ["micron", "--dump-config"]):
                main()

        mock_boot.assert_not_called()
