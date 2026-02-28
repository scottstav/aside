"""Tests for aside.models — model discovery."""

from __future__ import annotations

from unittest import mock

import pytest


class TestAvailableProviders:
    def test_returns_providers_with_env_keys(self):
        from aside.models import available_providers

        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
            providers = available_providers()
        assert "anthropic" in providers

    def test_excludes_providers_without_keys(self):
        from aside.models import available_providers

        env = {k: "" for k in [
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
            "GROQ_API_KEY", "MISTRAL_API_KEY", "COHERE_API_KEY",
            "TOGETHER_API_KEY", "DEEPSEEK_API_KEY",
        ]}
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch("aside.models.keyring_get_key", return_value=None):
                providers = available_providers()
        assert providers == []

    def test_finds_key_in_keyring(self):
        from aside.models import available_providers

        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("aside.models.keyring_get_key", side_effect=lambda p: "key" if p == "gemini" else None):
                providers = available_providers()
        assert providers == ["gemini"]


class TestAvailableModels:
    def test_filters_non_chat_models(self):
        from aside.models import available_models

        fake_registry = {
            "gemini": {
                "gemini/gemini-2.5-pro",
                "gemini/gemini-embedding-001",
                "gemini/imagen-4.0-generate-001",
                "gemini/gemini-2.5-flash-preview-tts",
            },
        }
        with mock.patch("aside.models._LITELLM_PROVIDERS", {"gemini": "gemini"}):
            with mock.patch("aside.models._get_registry", return_value=fake_registry):
                with mock.patch("aside.models.available_providers", return_value=["gemini"]):
                    result = available_models()

        assert result == {"gemini": ["gemini/gemini-2.5-pro"]}

    def test_normalizes_unprefixed_models(self):
        from aside.models import available_models

        fake_registry = {
            "anthropic": {"claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"},
        }
        with mock.patch("aside.models._LITELLM_PROVIDERS", {"anthropic": "anthropic"}):
            with mock.patch("aside.models._get_registry", return_value=fake_registry):
                with mock.patch("aside.models.available_providers", return_value=["anthropic"]):
                    result = available_models()

        # Both "claude-sonnet-4-6" and "anthropic/claude-sonnet-4-6" become "anthropic/claude-sonnet-4-6"
        assert result == {"anthropic": ["anthropic/claude-sonnet-4-6"]}

    def test_empty_when_no_keys(self):
        from aside.models import available_models

        with mock.patch("aside.models.available_providers", return_value=[]):
            result = available_models()
        assert result == {}
