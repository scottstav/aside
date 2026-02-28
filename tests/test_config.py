"""Tests for aside.config — TOML-based configuration system."""

import os
import textwrap
from pathlib import Path
from unittest import mock

import pytest


def _import_config():
    """Import config module from the package directory."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "aside.config", Path(__file__).parent.parent / "aside" / "config.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# DEFAULT_CONFIG structure
# ---------------------------------------------------------------------------


class TestDefaultConfig:
    """Verify DEFAULT_CONFIG has every required section and key."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.cfg = _import_config()
        self.defaults = self.cfg.DEFAULT_CONFIG

    def test_top_level_sections(self):
        expected = {
            "model", "input", "voice", "tts", "overlay",
            "storage", "plugins", "notifications", "status",
        }
        assert expected == set(self.defaults.keys())

    def test_model_defaults(self):
        m = self.defaults["model"]
        assert m["name"] == "anthropic/claude-sonnet-4-6"
        assert m["system_prompt"] == ""

    def test_input_defaults(self):
        assert self.defaults["input"]["terminal"] == "foot -e"

    def test_voice_defaults(self):
        v = self.defaults["voice"]
        assert v["enabled"] is False
        assert v["wake_word_model"] == ""
        assert v["wake_word_threshold"] == 0.5
        assert v["pre_roll_seconds"] == 0.5
        assert v["stt_model"] == "base"
        assert v["stt_device"] == "cpu"
        assert v["smart_silence"] is True
        assert v["silence_timeout"] == 2.5
        assert v["no_speech_timeout"] == 3.0
        assert v["force_send_phrases"] == ["send it", "that's it"]

    def test_tts_defaults(self):
        t = self.defaults["tts"]
        assert t["enabled"] is False
        assert t["model"] == "af_heart"
        assert t["speed"] == 1.0
        assert t["lang"] == "a"
        assert t["filter"]["skip_code_blocks"] is True
        assert t["filter"]["skip_urls"] is True

    def test_overlay_defaults(self):
        o = self.defaults["overlay"]
        assert o["font"] == "Sans 13"
        assert o["width"] == 600
        assert o["max_lines"] == 40
        assert o["margin_top"] == 10
        assert o["padding_x"] == 20
        assert o["padding_y"] == 16
        assert o["corner_radius"] == 12
        assert o["border_width"] == 2
        assert o["accent_height"] == 3
        assert o["scroll_duration"] == 200
        assert o["fade_duration"] == 400
        assert o["colors"]["background"] == "#1a1b26e6"
        assert o["colors"]["foreground"] == "#c0caf5ff"
        assert o["colors"]["border"] == "#414868ff"
        assert o["colors"]["accent"] == "#7aa2f7ff"

    def test_storage_defaults(self):
        s = self.defaults["storage"]
        assert s["conversations_dir"] == ""
        assert s["archive_dir"] == ""

    def test_plugins_defaults(self):
        assert self.defaults["plugins"]["dirs"] == []

    def test_notifications_defaults(self):
        n = self.defaults["notifications"]
        assert n == {}

    def test_status_defaults(self):
        assert self.defaults["status"]["signal"] == 12


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    """Verify recursive merge behavior."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.cfg = _import_config()

    def test_override_wins(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = self.cfg._deep_merge(base, override)
        assert result == {"a": 1, "b": 99}

    def test_nested_dict_merge(self):
        base = {"tts": {"enabled": False, "filter": {"skip_code_blocks": True, "skip_urls": True}}}
        override = {"tts": {"filter": {"skip_urls": False}}}
        result = self.cfg._deep_merge(base, override)
        assert result["tts"]["enabled"] is False
        assert result["tts"]["filter"]["skip_code_blocks"] is True
        assert result["tts"]["filter"]["skip_urls"] is False

    def test_non_dict_replaces(self):
        base = {"items": [1, 2, 3]}
        override = {"items": [4, 5]}
        result = self.cfg._deep_merge(base, override)
        assert result["items"] == [4, 5]

    def test_base_unchanged(self):
        base = {"a": {"x": 1}}
        override = {"a": {"x": 2}}
        self.cfg._deep_merge(base, override)
        assert base["a"]["x"] == 1, "deep_merge must not mutate the base dict"

    def test_new_keys_added(self):
        base = {"a": 1}
        override = {"b": 2}
        result = self.cfg._deep_merge(base, override)
        assert result == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """Verify TOML loading and merging."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.cfg = _import_config()

    def test_returns_defaults_when_no_file(self, tmp_path):
        nonexistent = tmp_path / "nope" / "config.toml"
        result = self.cfg.load_config(path=nonexistent)
        assert result == self.cfg.DEFAULT_CONFIG

    def test_merges_user_overrides(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [model]
            name = "openai/gpt-4o"

            [tts]
            speed = 1.5
        """))
        result = self.cfg.load_config(path=config_file)
        assert result["model"]["name"] == "openai/gpt-4o"
        assert result["model"]["system_prompt"] == ""  # preserved default
        assert result["tts"]["speed"] == 1.5
        assert result["tts"]["enabled"] is False  # preserved default
        assert result["tts"]["filter"]["skip_code_blocks"] is True  # nested default preserved

    def test_merges_nested_overrides(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(textwrap.dedent("""\
            [tts.filter]
            skip_urls = false
        """))
        result = self.cfg.load_config(path=config_file)
        assert result["tts"]["filter"]["skip_urls"] is False
        assert result["tts"]["filter"]["skip_code_blocks"] is True

    def test_xdg_config_home_resolution(self, tmp_path):
        """load_config(path=None) resolves via XDG_CONFIG_HOME."""
        config_dir = tmp_path / "aside"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text('[model]\nname = "test/model"\n')

        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
            result = self.cfg.load_config()
        assert result["model"]["name"] == "test/model"

    def test_xdg_config_home_fallback(self, tmp_path):
        """Without XDG_CONFIG_HOME, falls back to ~/.config/aside/config.toml."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("pathlib.Path.home", return_value=tmp_path):
                result = self.cfg.load_config()
        # No config file exists at tmp_path/.config/aside/config.toml, so defaults
        assert result == self.cfg.DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# resolve_* helpers
# ---------------------------------------------------------------------------


class TestResolveHelpers:
    """Verify XDG path resolution functions."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.cfg = _import_config()

    def test_resolve_state_dir_with_env(self, tmp_path):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(tmp_path)}):
            result = self.cfg.resolve_state_dir(self.cfg.DEFAULT_CONFIG)
        assert result == tmp_path / "aside"

    def test_resolve_state_dir_fallback(self, tmp_path):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("pathlib.Path.home", return_value=tmp_path):
                result = self.cfg.resolve_state_dir(self.cfg.DEFAULT_CONFIG)
        assert result == tmp_path / ".local" / "state" / "aside"

    def test_resolve_conversations_dir_default(self, tmp_path):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(tmp_path)}):
            result = self.cfg.resolve_conversations_dir(self.cfg.DEFAULT_CONFIG)
        assert result == tmp_path / "aside" / "conversations"

    def test_resolve_conversations_dir_custom(self):
        custom = {"storage": {"conversations_dir": "/tmp/my-convos"}}
        result = self.cfg.resolve_conversations_dir(custom)
        assert result == Path("/tmp/my-convos")

    def test_resolve_socket_path_with_runtime_dir(self, tmp_path):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(tmp_path)}):
            result = self.cfg.resolve_socket_path()
        assert result == tmp_path / "aside.sock"

    def test_resolve_socket_path_custom_name(self, tmp_path):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(tmp_path)}):
            result = self.cfg.resolve_socket_path("custom.sock")
        assert result == tmp_path / "custom.sock"

    def test_resolve_socket_path_fallback(self):
        uid = os.getuid()
        with mock.patch.dict(os.environ, {}, clear=True):
            result = self.cfg.resolve_socket_path()
        assert result == Path(f"/run/user/{uid}/aside.sock")
