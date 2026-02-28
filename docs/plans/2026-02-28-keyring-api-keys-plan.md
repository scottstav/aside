# Keyring API Key Retrieval — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add KWallet and GNOME Keyring support for API key retrieval, with EnvironmentFile as a systemd-level fallback, plus CLI commands for key management.

**Architecture:** New `aside/keyring.py` module uses subprocess calls to `kwalletcli` and `secret-tool` CLI tools — no Python keyring dependencies. The daemon startup chain becomes: env var > KWallet > GNOME Keyring > runtime cache. A new `aside set-key` CLI command stores keys in the first available backend.

**Tech Stack:** Python 3.11+, subprocess (`kwalletcli`, `secret-tool`), systemd EnvironmentFile

---

### Task 1: Create `aside/keyring.py` — backend detection and key retrieval

**Files:**
- Create: `aside/keyring.py`
- Create: `tests/test_keyring.py`

**Step 1: Write the failing tests for backend detection**

```python
"""Tests for aside.keyring — desktop keyring integration."""

from __future__ import annotations

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
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_keyring.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'aside.keyring'`

**Step 3: Write the minimal implementation for backend detection**

```python
"""Desktop keyring integration — KWallet and GNOME Keyring via subprocess."""

from __future__ import annotations

import logging
import shutil

log = logging.getLogger("aside")


def _kwallet_available() -> bool:
    """Check if kwalletcli tools are installed."""
    return shutil.which("kwalletcli-getentry") is not None


def _gnome_available() -> bool:
    """Check if GNOME secret-tool is installed."""
    return shutil.which("secret-tool") is not None
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_keyring.py -x -q`
Expected: 4 passed

**Step 5: Commit**

```
git add aside/keyring.py tests/test_keyring.py
git commit -m "feat(keyring): add backend detection for KWallet and GNOME Keyring"
```

---

### Task 2: Key retrieval — `get_key()`

**Files:**
- Modify: `aside/keyring.py`
- Modify: `tests/test_keyring.py`

**Step 1: Write the failing tests for get_key**

Append to `tests/test_keyring.py`:

```python
import subprocess

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
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_keyring.py::TestGetKey -x -q`
Expected: FAIL — `ImportError: cannot import name 'get_key'`

**Step 3: Implement get_key**

Add to `aside/keyring.py`:

```python
import subprocess


def get_key(provider: str) -> str | None:
    """Retrieve an API key from the first available desktop keyring.

    Tries KWallet first, then GNOME Keyring.  Returns None if neither
    backend is available or the key isn't stored.
    """
    if _kwallet_available():
        try:
            result = subprocess.run(
                ["kwalletcli-getentry", "-f", "aside", "-e", f"{provider}-api-key"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                log.info("Retrieved %s key from KWallet", provider)
                return result.stdout.strip()
        except subprocess.TimeoutExpired:
            log.warning("KWallet lookup timed out for %s", provider)

    if _gnome_available():
        try:
            result = subprocess.run(
                ["secret-tool", "lookup", "service", "aside", "provider", provider],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                log.info("Retrieved %s key from GNOME Keyring", provider)
                return result.stdout.strip()
        except subprocess.TimeoutExpired:
            log.warning("secret-tool lookup timed out for %s", provider)

    return None
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_keyring.py -x -q`
Expected: all passed

**Step 5: Commit**

```
git add aside/keyring.py tests/test_keyring.py
git commit -m "feat(keyring): add get_key() with KWallet and GNOME Keyring support"
```

---

### Task 3: Key storage — `set_key()`

**Files:**
- Modify: `aside/keyring.py`
- Modify: `tests/test_keyring.py`

**Step 1: Write the failing tests for set_key**

Append to `tests/test_keyring.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_keyring.py::TestSetKey -x -q`
Expected: FAIL — `ImportError: cannot import name 'set_key'`

**Step 3: Implement set_key and helpers**

Add to `aside/keyring.py`:

```python
import os
from pathlib import Path


# Provider name <-> env var mapping.
_PROVIDER_TO_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "together": "TOGETHER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

_ENV_TO_PROVIDER = {v: k for k, v in _PROVIDER_TO_ENV.items()}


def _env_file_path() -> Path:
    """Return path to the EnvironmentFile (~/.config/aside/env)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "aside" / "env"
    return Path.home() / ".config" / "aside" / "env"


def set_key(provider: str, key: str) -> str:
    """Store an API key in the first available backend.

    Returns the backend name: 'kwallet', 'gnome-keyring', or 'env-file'.
    """
    if _kwallet_available():
        try:
            result = subprocess.run(
                ["kwalletcli-setentry", "-f", "aside", "-e", f"{provider}-api-key"],
                input=key,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                log.info("Stored %s key in KWallet", provider)
                return "kwallet"
        except subprocess.TimeoutExpired:
            log.warning("KWallet store timed out for %s", provider)

    if _gnome_available():
        try:
            result = subprocess.run(
                [
                    "secret-tool", "store",
                    f"--label=aside: {provider} API key",
                    "service", "aside",
                    "provider", provider,
                ],
                input=key,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                log.info("Stored %s key in GNOME Keyring", provider)
                return "gnome-keyring"
        except subprocess.TimeoutExpired:
            log.warning("secret-tool store timed out for %s", provider)

    # Fall back to env file
    env_var = _PROVIDER_TO_ENV.get(provider, f"{provider.upper()}_API_KEY")
    env_file = _env_file_path()
    env_file.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if not line.startswith(f"{env_var}="):
                lines.append(line)
    lines.append(f"{env_var}={key}")

    env_file.write_text("\n".join(lines) + "\n")
    env_file.chmod(0o600)
    log.info("Stored %s key in %s", provider, env_file)
    return "env-file"
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_keyring.py -x -q`
Expected: all passed

**Step 5: Commit**

```
git add aside/keyring.py tests/test_keyring.py
git commit -m "feat(keyring): add set_key() with env-file fallback"
```

---

### Task 4: Daemon integration — `load_keyring_keys()`

**Files:**
- Modify: `aside/keyring.py`
- Modify: `aside/daemon.py:463-464`
- Modify: `tests/test_keyring.py`
- Modify: `tests/test_daemon.py`

**Step 1: Write the failing tests for load_keyring_keys**

Append to `tests/test_keyring.py`:

```python
import os

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
            with mock.patch("aside.keyring.get_key") as mock_get:
                load_keyring_keys()

            # Should not even attempt to look up anthropic
            for call in mock_get.call_args_list:
                assert call[0][0] != "anthropic"
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_keyring.py::TestLoadKeyringKeys -x -q`
Expected: FAIL — `ImportError: cannot import name 'load_keyring_keys'`

**Step 3: Implement load_keyring_keys**

Add to `aside/keyring.py`:

```python
def load_keyring_keys() -> None:
    """Load API keys from desktop keyrings into env vars.

    Only sets vars that aren't already in the environment.
    Called during daemon startup, after _restore_api_keys() and before
    _cache_api_keys().
    """
    for env_var, provider in _ENV_TO_PROVIDER.items():
        if env_var in os.environ:
            continue
        key = get_key(provider)
        if key:
            os.environ[env_var] = key
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_keyring.py -x -q`
Expected: all passed

**Step 5: Wire into daemon startup**

Modify `aside/daemon.py:456-466`. Change `main()` from:

```python
def main() -> None:
    """CLI entry point: load config and run the daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    _restore_api_keys()
    _cache_api_keys()
    config = load_config()
    Daemon(config).run()
```

to:

```python
def main() -> None:
    """CLI entry point: load config and run the daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    _restore_api_keys()

    from aside.keyring import load_keyring_keys
    load_keyring_keys()

    _cache_api_keys()
    config = load_config()
    Daemon(config).run()
```

**Step 6: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: all passed

**Step 7: Commit**

```
git add aside/keyring.py aside/daemon.py tests/test_keyring.py
git commit -m "feat(keyring): wire load_keyring_keys() into daemon startup"
```

---

### Task 5: CLI commands — `set-key` and `get-key`

**Files:**
- Modify: `aside/cli.py:67-138` (parser), `aside/cli.py:413-424` (handlers)
- Modify: `tests/test_cli.py`

**Step 1: Write failing tests for argument parsing**

Append to the `TestArgumentParsing` class in `tests/test_cli.py`:

```python
    def test_set_key_basic(self):
        args = self.parser.parse_args(["set-key", "anthropic", "sk-test"])
        assert args.command == "set-key"
        assert args.provider == "anthropic"
        assert args.key == "sk-test"

    def test_set_key_no_key_arg(self):
        args = self.parser.parse_args(["set-key", "openai"])
        assert args.command == "set-key"
        assert args.provider == "openai"
        assert args.key is None

    def test_get_key_basic(self):
        args = self.parser.parse_args(["get-key", "anthropic"])
        assert args.command == "get-key"
        assert args.provider == "anthropic"
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::TestArgumentParsing::test_set_key_basic -x -q`
Expected: FAIL — `error: argument command: invalid choice: 'set-key'`

**Step 3: Add subcommands to the parser**

In `aside/cli.py`, inside `_build_parser()`, after the `ls` subparser (around line 137), add:

```python
    # aside set-key PROVIDER [KEY]
    sk = sub.add_parser("set-key", help="Store an API key in the system keyring")
    sk.add_argument("provider", help="Provider name (anthropic, openai, etc.)")
    sk.add_argument("key", nargs="?", default=None, help="API key (reads stdin if omitted)")

    # aside get-key PROVIDER
    gk = sub.add_parser("get-key", help="Show a stored API key (masked)")
    gk.add_argument("provider", help="Provider name (anthropic, openai, etc.)")
```

**Step 4: Run parser tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::TestArgumentParsing -x -q`
Expected: all passed

**Step 5: Write failing tests for the handler functions**

Append to `tests/test_cli.py`:

```python
from aside.cli import _cmd_set_key, _cmd_get_key


class TestSetKeyCommand:
    def test_set_key_with_arg(self, capsys):
        args = mock.Mock(provider="anthropic", key="sk-123")
        with mock.patch("aside.keyring.set_key", return_value="kwallet") as mock_set:
            _cmd_set_key(args)
        mock_set.assert_called_once_with("anthropic", "sk-123")
        assert "kwallet" in capsys.readouterr().out

    def test_set_key_from_stdin(self, capsys):
        args = mock.Mock(provider="openai", key=None)
        with mock.patch("aside.keyring.set_key", return_value="gnome-keyring") as mock_set:
            with mock.patch("sys.stdin") as mock_stdin:
                mock_stdin.read.return_value = "sk-stdin-key\n"
                _cmd_set_key(args)
        mock_set.assert_called_once_with("openai", "sk-stdin-key")


class TestGetKeyCommand:
    def test_get_key_found(self, capsys):
        args = mock.Mock(provider="anthropic")
        with mock.patch("aside.keyring.get_key", return_value="sk-ant-1234567890abcdef"):
            _cmd_get_key(args)
        out = capsys.readouterr().out
        assert "sk-a...cdef" in out

    def test_get_key_not_found(self, capsys):
        args = mock.Mock(provider="openai")
        with mock.patch("aside.keyring.get_key", return_value=None):
            with mock.patch("aside.keyring._PROVIDER_TO_ENV", {"openai": "OPENAI_API_KEY"}):
                with mock.patch.dict(os.environ, {}, clear=True):
                    _cmd_get_key(args)
        out = capsys.readouterr().out
        assert "not found" in out.lower()
```

**Step 6: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::TestSetKeyCommand -x -q`
Expected: FAIL — `ImportError: cannot import name '_cmd_set_key'`

**Step 7: Implement the handler functions**

Add to `aside/cli.py`, before the `_HANDLERS` dict:

```python
def _cmd_set_key(args: argparse.Namespace) -> None:
    """Store an API key in the system keyring."""
    import aside.keyring

    key = args.key
    if key is None:
        key = sys.stdin.read().strip()
    if not key:
        print("Error: no key provided", file=sys.stderr)
        sys.exit(1)

    backend = aside.keyring.set_key(args.provider, key)
    print(f"Stored {args.provider} key in {backend}")


def _cmd_get_key(args: argparse.Namespace) -> None:
    """Show a stored API key (masked)."""
    import os
    import aside.keyring

    # Check env first, then keyring
    env_var = aside.keyring._PROVIDER_TO_ENV.get(
        args.provider, f"{args.provider.upper()}_API_KEY"
    )
    key = os.environ.get(env_var) or aside.keyring.get_key(args.provider)

    if key:
        # Mask: show first 4 and last 4 chars
        if len(key) > 10:
            masked = key[:4] + "..." + key[-4:]
        else:
            masked = key[:2] + "..." + key[-2:]
        print(f"{args.provider}: {masked}")
    else:
        print(f"{args.provider}: not found")
```

Add to `_HANDLERS` dict:

```python
    "set-key": _cmd_set_key,
    "get-key": _cmd_get_key,
```

**Step 8: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -x -q`
Expected: all passed

**Step 9: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: all passed

**Step 10: Commit**

```
git add aside/cli.py tests/test_cli.py
git commit -m "feat(cli): add set-key and get-key subcommands"
```

---

### Task 6: SystemD EnvironmentFile

**Files:**
- Modify: `data/aside-daemon.service`

**Step 1: Add EnvironmentFile directive**

In `data/aside-daemon.service`, add `EnvironmentFile` line after the existing `Environment` line. The `[Service]` section should become:

```ini
[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-%h/.config/aside/env
ExecStart=%h/.local/lib/aside/venv/bin/python3 -m aside.daemon
Restart=on-failure
RestartSec=5
```

The `-` prefix means systemd won't fail if the file doesn't exist.

**Step 2: Commit**

```
git add data/aside-daemon.service
git commit -m "feat(systemd): add EnvironmentFile for API key env file"
```

---

### Task 7: Update documentation

**Files:**
- Modify: `docs/configuration.md:214-246`
- Modify: `docs/install.md:12-19`

**Step 1: Update docs/configuration.md**

Replace the "Environment variables" section (lines 214-246) with:

```markdown
## API key configuration

Aside needs an API key for your chosen LLM provider. Keys are resolved in this order:

1. **Environment variable** — set directly or via systemd EnvironmentFile
2. **KWallet** — queried via `kwalletcli-getentry`
3. **GNOME Keyring** — queried via `secret-tool`
4. **Runtime cache** — `$XDG_RUNTIME_DIR/aside-api-keys` (survives daemon restarts)

### Supported provider keys

| Variable | When needed |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic models (`anthropic/claude-*`) |
| `OPENAI_API_KEY` | OpenAI models (`openai/gpt-*`) |
| `GEMINI_API_KEY` | Google Gemini models |
| `GROQ_API_KEY` | Groq models |
| `MISTRAL_API_KEY` | Mistral models |
| `DEEPSEEK_API_KEY` | DeepSeek models |
| `TOGETHER_API_KEY` | Together AI models |
| `COHERE_API_KEY` | Cohere models |

For local models via Ollama, no API key is needed — just set `model.name = "ollama/llama3"`.

### Using the CLI (recommended)

```bash
aside set-key anthropic sk-ant-...
aside set-key openai sk-...
```

This stores the key in KWallet or GNOME Keyring (whichever is available), falling back to `~/.config/aside/env`. To verify:

```bash
aside get-key anthropic
# anthropic: sk-a...xyz
```

### Using a desktop keyring manually

**KWallet:**

```bash
echo -n "sk-..." | kwalletcli-setentry -f aside -e anthropic-api-key
```

**GNOME Keyring:**

```bash
echo -n "sk-..." | secret-tool store --label='aside: anthropic API key' service aside provider anthropic
```

### Using an environment file

Create `~/.config/aside/env` (mode 0600):

```bash
ANTHROPIC_API_KEY=sk-...
```

The systemd unit loads this file automatically via `EnvironmentFile`. For shell use, source it: `. ~/.config/aside/env`.

### Using environment variables directly

```bash
export ANTHROPIC_API_KEY="sk-..."
```

Or in a systemd override (`systemctl --user edit aside-daemon`):

```ini
[Service]
Environment=ANTHROPIC_API_KEY=sk-...
```
```

**Step 2: Update docs/install.md**

Replace lines 12-19 (the API key section) with:

```markdown
Copy the example config and set your API key:

```bash
cp ~/.config/aside/config.toml.example ~/.config/aside/config.toml
# Edit config.toml — at minimum set model.name
aside set-key anthropic sk-ant-...   # or: aside set-key openai sk-...
```

See [configuration.md](configuration.md#api-key-configuration) for all key storage options (keyring, env file, env vars).
```

**Step 3: Update the File paths table in docs/configuration.md**

Add `~/.config/aside/env` to the file paths table:

```markdown
| `~/.config/aside/env` | API key environment file (loaded by systemd) |
```

**Step 4: Commit**

```
git add docs/configuration.md docs/install.md
git commit -m "docs: document keyring integration, env file, and set-key CLI"
```

---

### Task 8: Final integration test

**Step 1: Run the full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: all 248+ tests pass

**Step 2: Verify CLI help output**

Run: `source .venv/bin/activate && aside --help`
Expected: `set-key` and `get-key` appear in the subcommand list

Run: `source .venv/bin/activate && aside set-key --help`
Expected: shows provider and key arguments

**Step 3: Final commit if any fixups needed**
