"""Tests for aside.status — waybar status bar module."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from aside.status import main, _extract_model_name, _build_output


# ---------------------------------------------------------------------------
# Model name extraction
# ---------------------------------------------------------------------------


class TestModelNameExtraction:
    """Verify LiteLLM provider/model format parsing."""

    def test_anthropic_sonnet(self):
        assert _extract_model_name("anthropic/claude-sonnet-4-6") == "Sonnet 4.6"

    def test_anthropic_opus(self):
        assert _extract_model_name("anthropic/claude-opus-4-6") == "Opus 4.6"

    def test_anthropic_haiku(self):
        assert _extract_model_name("anthropic/claude-haiku-4-5") == "Haiku 4.5"

    def test_openai_model(self):
        assert _extract_model_name("openai/gpt-4o") == "gpt-4o"

    def test_no_provider_prefix(self):
        """Model without provider/ prefix should be returned as-is."""
        assert _extract_model_name("claude-sonnet-4-6") == "Sonnet 4.6"

    def test_unknown_provider(self):
        assert _extract_model_name("deepseek/deepseek-chat") == "deepseek-chat"

    def test_empty_string(self):
        assert _extract_model_name("") == ""

    def test_claude_with_version_digits(self):
        """Version parts after the family name should be joined with dots."""
        assert _extract_model_name("anthropic/claude-sonnet-4-6") == "Sonnet 4.6"

    def test_claude_three_digit_version(self):
        """Hypothetical three-digit version."""
        assert _extract_model_name("anthropic/claude-sonnet-4-6-1") == "Sonnet 4.6.1"


# ---------------------------------------------------------------------------
# Output building
# ---------------------------------------------------------------------------


class TestBuildOutput:
    """Verify JSON output structure for waybar."""

    def _make_status(self, **overrides):
        base = {
            "status": "idle",
            "model": "anthropic/claude-sonnet-4-6",
            "tool_name": "",
            "speak_enabled": False,
            "usage": {
                "month_cost": "$0.00",
                "last_query_cost": "$0.00",
                "total_tokens": 0,
            },
        }
        base.update(overrides)
        return base

    def test_idle_output(self):
        result = _build_output(self._make_status())
        assert result["class"] == "idle"
        assert "text" in result
        assert "tooltip" in result

    def test_thinking_output(self):
        result = _build_output(self._make_status(status="thinking"))
        assert result["class"] == "thinking"

    def test_speaking_output(self):
        result = _build_output(self._make_status(status="speaking"))
        assert result["class"] == "speaking"

    def test_tool_use_output(self):
        result = _build_output(self._make_status(status="tool_use", tool_name="web_search"))
        assert result["class"] == "tool_use"
        assert "web_search" in result["tooltip"]

    def test_idle_tooltip_contains_model(self):
        result = _build_output(self._make_status())
        assert "Sonnet 4.6" in result["tooltip"]

    def test_idle_tooltip_contains_cost(self):
        result = _build_output(self._make_status(
            usage={"month_cost": "$12.34", "last_query_cost": "$0.05", "total_tokens": 5000}
        ))
        assert "$12.34" in result["tooltip"]

    def test_output_is_valid_json_serializable(self):
        result = _build_output(self._make_status())
        # Should not raise
        output = json.dumps(result)
        parsed = json.loads(output)
        assert parsed == result

    def test_text_is_nonempty(self):
        """Every status should produce some icon text."""
        for status in ("idle", "thinking", "speaking", "tool_use"):
            result = _build_output(self._make_status(status=status))
            assert result["text"], f"Empty text for status={status}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


class TestMain:
    """Test the main() entry point that reads status.json and prints."""

    def test_main_prints_json(self, tmp_path, capsys):
        state_dir = tmp_path / "aside"
        state_dir.mkdir()
        status_data = {
            "status": "idle",
            "model": "anthropic/claude-sonnet-4-6",
            "tool_name": "",
            "speak_enabled": False,
            "usage": {"month_cost": "$0.00", "last_query_cost": "$0.00", "total_tokens": 0},
        }
        (state_dir / "status.json").write_text(json.dumps(status_data))

        cfg = {"status": {"signal": 12}}

        with mock.patch("aside.status.load_config", return_value=cfg):
            with mock.patch("aside.status.resolve_state_dir", return_value=state_dir):
                main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "text" in output
        assert "tooltip" in output
        assert "class" in output

    def test_main_missing_status_file(self, tmp_path, capsys):
        """When status.json doesn't exist, output idle with not-running tooltip."""
        state_dir = tmp_path / "aside"
        state_dir.mkdir()

        cfg = {"status": {"signal": 12}}

        with mock.patch("aside.status.load_config", return_value=cfg):
            with mock.patch("aside.status.resolve_state_dir", return_value=state_dir):
                main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["class"] == "idle"
        assert "not running" in output["tooltip"].lower()

    def test_main_corrupted_status_file(self, tmp_path, capsys):
        """Corrupted status.json should produce fallback output."""
        state_dir = tmp_path / "aside"
        state_dir.mkdir()
        (state_dir / "status.json").write_text("not valid json {{{")

        cfg = {"status": {"signal": 12}}

        with mock.patch("aside.status.load_config", return_value=cfg):
            with mock.patch("aside.status.resolve_state_dir", return_value=state_dir):
                main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["class"] == "idle"
