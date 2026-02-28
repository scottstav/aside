"""Tests for aside.keyring — desktop keyring integration."""

from __future__ import annotations

import os
import subprocess
from unittest import mock

import pytest

from aside.keyring import _kwallet_available, _gnome_available


class TestBackendDetection:
    def test_kwallet_available_when_installed(self):
        with mock.patch("shutil.which", return_value="/usr/bin/kwalletcli-getentry"):
            assert _kwallet_available() is True

    def test_kwallet_unavailable_when_missing(self):
        with mock.patch("shutil.which", return_value=None):
            assert _kwallet_available() is False

    def test_gnome_available_when_installed(self):
        with mock.patch("shutil.which", return_value="/usr/bin/secret-tool"):
            assert _gnome_available() is True

    def test_gnome_unavailable_when_missing(self):
        with mock.patch("shutil.which", return_value=None):
            assert _gnome_available() is False


from aside.keyring import get_key


class TestGetKey:
    def test_kwallet_returns_key(self):
        """get_key tries KWallet first."""
        with mock.patch("aside.keyring._kwallet_available", return_value=True):
            with mock.patch("aside.keyring._gnome_available", return_value=False):
                with mock.patch(
                    "subprocess.run",
                    return_value=mock.Mock(returncode=0, stdout="sk-test-key\n"),
                ) as mock_run:
                    result = get_key("anthropic")

        assert result == "sk-test-key"
        mock_run.assert_called_once_with(
            ["kwalletcli-getentry", "-f", "aside", "-e", "anthropic-api-key"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_gnome_fallback_when_kwallet_unavailable(self):
        """get_key falls back to GNOME when KWallet isn't installed."""
        with mock.patch("aside.keyring._kwallet_available", return_value=False):
            with mock.patch("aside.keyring._gnome_available", return_value=True):
                with mock.patch(
                    "subprocess.run",
                    return_value=mock.Mock(returncode=0, stdout="sk-gnome-key\n"),
                ) as mock_run:
                    result = get_key("openai")

        assert result == "sk-gnome-key"
        mock_run.assert_called_once_with(
            ["secret-tool", "lookup", "service", "aside", "provider", "openai"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_gnome_fallback_when_kwallet_fails(self):
        """get_key falls back to GNOME when KWallet returns non-zero."""
        kwallet_fail = mock.Mock(returncode=1, stdout="")
        gnome_ok = mock.Mock(returncode=0, stdout="sk-gnome\n")
        with mock.patch("aside.keyring._kwallet_available", return_value=True):
            with mock.patch("aside.keyring._gnome_available", return_value=True):
                with mock.patch(
                    "subprocess.run", side_effect=[kwallet_fail, gnome_ok]
                ):
                    result = get_key("anthropic")

        assert result == "sk-gnome"

    def test_returns_none_when_no_backend(self):
        """get_key returns None when no backend is available."""
        with mock.patch("aside.keyring._kwallet_available", return_value=False):
            with mock.patch("aside.keyring._gnome_available", return_value=False):
                result = get_key("anthropic")

        assert result is None

    def test_returns_none_when_all_fail(self):
        """get_key returns None when all backends fail."""
        fail = mock.Mock(returncode=1, stdout="")
        with mock.patch("aside.keyring._kwallet_available", return_value=True):
            with mock.patch("aside.keyring._gnome_available", return_value=True):
                with mock.patch("subprocess.run", return_value=fail):
                    result = get_key("anthropic")

        assert result is None

    def test_handles_subprocess_timeout(self):
        """get_key handles subprocess timeout gracefully."""
        with mock.patch("aside.keyring._kwallet_available", return_value=True):
            with mock.patch("aside.keyring._gnome_available", return_value=False):
                with mock.patch(
                    "subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)
                ):
                    result = get_key("anthropic")

        assert result is None


from aside.keyring import set_key


class TestSetKey:
    def test_stores_in_kwallet(self):
        with mock.patch("aside.keyring._kwallet_available", return_value=True):
            with mock.patch(
                "subprocess.run",
                return_value=mock.Mock(returncode=0),
            ) as mock_run:
                backend = set_key("anthropic", "sk-test-123")

        assert backend == "kwallet"
        mock_run.assert_called_once_with(
            ["kwalletcli-setentry", "-f", "aside", "-e", "anthropic-api-key"],
            input="sk-test-123",
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_falls_back_to_gnome(self):
        with mock.patch("aside.keyring._kwallet_available", return_value=False):
            with mock.patch("aside.keyring._gnome_available", return_value=True):
                with mock.patch(
                    "subprocess.run",
                    return_value=mock.Mock(returncode=0),
                ) as mock_run:
                    backend = set_key("openai", "sk-openai-456")

        assert backend == "gnome-keyring"
        mock_run.assert_called_once_with(
            [
                "secret-tool", "store",
                "--label=aside: openai API key",
                "service", "aside",
                "provider", "openai",
            ],
            input="sk-openai-456",
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_falls_back_to_env_file(self, tmp_path):
        env_file = tmp_path / "env"
        with mock.patch("aside.keyring._kwallet_available", return_value=False):
            with mock.patch("aside.keyring._gnome_available", return_value=False):
                with mock.patch("aside.keyring._env_file_path", return_value=env_file):
                    backend = set_key("anthropic", "sk-file-789")

        assert backend == "env-file"
        content = env_file.read_text()
        assert "ANTHROPIC_API_KEY=sk-file-789\n" in content

    def test_env_file_updates_existing_key(self, tmp_path):
        env_file = tmp_path / "env"
        env_file.write_text("ANTHROPIC_API_KEY=old-key\nOPENAI_API_KEY=keep-this\n")
        with mock.patch("aside.keyring._kwallet_available", return_value=False):
            with mock.patch("aside.keyring._gnome_available", return_value=False):
                with mock.patch("aside.keyring._env_file_path", return_value=env_file):
                    set_key("anthropic", "new-key")

        content = env_file.read_text()
        assert "ANTHROPIC_API_KEY=new-key\n" in content
        assert "OPENAI_API_KEY=keep-this\n" in content
        assert "old-key" not in content


from aside.keyring import load_keyring_keys, _PROVIDER_TO_ENV


class TestLoadKeyringKeys:
    def test_loads_missing_keys_from_keyring(self):
        """load_keyring_keys should set env vars for keys not already present."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "aside.keyring.get_key",
                side_effect=lambda p: "sk-test" if p == "anthropic" else None,
            ):
                load_keyring_keys()

            assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test"
            assert "OPENAI_API_KEY" not in os.environ

    def test_does_not_overwrite_existing_env(self):
        """Existing env vars should not be overwritten."""
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "existing"}, clear=True):
            with mock.patch("aside.keyring.get_key", return_value=None) as mock_get:
                load_keyring_keys()

            # Should not even attempt to look up anthropic
            for call in mock_get.call_args_list:
                assert call[0][0] != "anthropic"
