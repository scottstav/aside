# Model Management & Config Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `aside models` and `aside model set` CLI commands, and eliminate all runtime config re-reads from the daemon.

**Architecture:** New `aside/models.py` module for model discovery via LiteLLM registry filtered by available API keys. Two new CLI subcommands. Two new daemon socket actions (`get_model`, `set_model`). Config cleanup removes all per-query disk reads — config loads once at startup, everything mutable lives in memory.

**Tech Stack:** Python 3.11+, LiteLLM (`litellm.models_by_provider`), existing keyring module, UNIX socket IPC.

---

### Task 1: Config cleanup — remove runtime config re-reads

**Files:**
- Modify: `aside/state.py:293-308` (delete `reload_model`, `reload_speak_enabled`, `_read_model_from_config`)
- Modify: `aside/state.py:10` (remove `tomllib` import)
- Modify: `aside/daemon.py:181-182` (remove `config_path` param)
- Modify: `aside/daemon.py:241-251` (delete `_reload_model`)
- Modify: `aside/daemon.py:264` (remove `_reload_model()` call)
- Modify: `aside/daemon.py:499-501` (stop passing `config_path`)
- Modify: `aside/query.py:424` (remove `reload_speak_enabled()` call)
- Modify: `tests/test_state.py:293-307` (delete `test_reload_model`, `test_reload_model_missing_file`)
- Test: `tests/test_state.py`, `tests/test_query.py`

**Step 1: Delete `_read_model_from_config` and `reload_model` from state.py**

In `aside/state.py`, delete the `reload_model` method (lines 293-297), `reload_speak_enabled` method (lines 299-308), and `_read_model_from_config` function (lines 336-343). Also remove the `tomllib` import (line 10) since it's only used by `_read_model_from_config`. Add a `set_model` method to `StatusState`:

```python
def set_model(self, model: str) -> None:
    """Update the active model name in status state."""
    with self._lock:
        self._state["model"] = model
        self._write()
```

**Step 2: Remove `_reload_model` and `config_path` from daemon.py**

In `aside/daemon.py`:

1. Delete the `_reload_model` method (lines 241-251).
2. Remove `config_path` from `__init__` signature and `self._config_path` (lines 181-183).
3. Remove the `self._reload_model()` call in `start_query` (line 264).
4. In `main()` (line 501), change `Daemon(config, config_path=config_path).run()` to `Daemon(config).run()`. Remove `config_path = _resolve_config_path()` and `_resolve_config_path` function (lines 499, 504-509) — they're no longer needed since `load_config()` handles path resolution internally.

```python
def main() -> None:
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

**Step 3: Remove `reload_speak_enabled` call from query.py**

In `aside/query.py`, line 424, remove `status.reload_speak_enabled()`. The speak state is already managed in memory via the `toggle_tts` socket action. The TTS section becomes:

```python
    speak_on = False
    if tts is not None:
        speak_on = status.speak_enabled
```

**Step 4: Update tests**

In `tests/test_state.py`:
- Delete `test_reload_model` (line 293) and `test_reload_model_missing_file` (line 301).
- Add `test_set_model`:

```python
def test_set_model(self):
    with mock.patch("subprocess.Popen"):
        self.status.set_model("gemini/gemini-2.5-pro")
    data = json.loads((self.state_dir / "status.json").read_text())
    assert data["model"] == "gemini/gemini-2.5-pro"
```

**Step 5: Run tests to verify cleanup**

Run: `source .venv/bin/activate && python -m pytest tests/test_state.py tests/test_query.py tests/test_cli.py -x -q`
Expected: All pass.

**Step 6: Commit**

```
git add aside/state.py aside/daemon.py aside/query.py tests/test_state.py
git commit -m "refactor: remove runtime config re-reads, config loads once at startup"
```

---

### Task 2: Add `_send_recv` to CLI for request-response socket calls

**Files:**
- Modify: `aside/cli.py:21-39` (add `_send_recv` alongside `_send`)
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

In `tests/test_cli.py`, add:

```python
class TestSendRecv:
    def test_send_recv_returns_response(self, tmp_path):
        """_send_recv sends JSON and returns the parsed JSON response."""
        import asyncio

        sock_path = tmp_path / "test.sock"

        async def echo_server():
            async def handler(reader, writer):
                data = await reader.read(65536)
                writer.write(data)
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            srv = await asyncio.start_unix_server(handler, path=str(sock_path))
            return srv

        async def run():
            srv = await echo_server()
            try:
                from aside.cli import _send_recv
                with mock.patch("aside.cli.resolve_socket_path", return_value=sock_path):
                    result = _send_recv({"action": "get_model"})
                assert result == {"action": "get_model"}
            finally:
                srv.close()
                await srv.wait_closed()

        asyncio.run(run())

    def test_send_recv_daemon_not_running(self, tmp_path):
        from aside.cli import _send_recv
        with mock.patch("aside.cli.resolve_socket_path", return_value=tmp_path / "nope.sock"):
            with pytest.raises(SystemExit):
                _send_recv({"action": "get_model"})
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::TestSendRecv -x -v`
Expected: FAIL (ImportError, `_send_recv` doesn't exist yet)

**Step 3: Write `_send_recv` in cli.py**

Add after the existing `_send` function:

```python
def _send_recv(msg: dict) -> dict:
    """Send JSON to the daemon and return the JSON response.

    Like _send, but waits for a response before closing.
    """
    sock_path = resolve_socket_path("aside.sock")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(sock_path))
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        print("Error: aside daemon is not running", file=sys.stderr)
        sys.exit(1)

    try:
        sock.sendall(json.dumps(msg).encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)

        chunks = []
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)

        return json.loads(b"".join(chunks).decode("utf-8"))
    finally:
        sock.close()
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::TestSendRecv -x -v`
Expected: PASS

**Step 5: Commit**

```
git add aside/cli.py tests/test_cli.py
git commit -m "feat: add _send_recv for request-response daemon IPC"
```

---

### Task 3: Add `get_model` and `set_model` socket actions to daemon

**Files:**
- Modify: `aside/daemon.py` (handle_client, add response writing)
- Test: `tests/test_cli.py` (integration-style test via daemon)

**Step 1: Write the failing test**

In `tests/test_cli.py`, add:

```python
class TestDaemonModelActions:
    """Test get_model and set_model socket actions."""

    @pytest.fixture
    def daemon(self, tmp_path):
        from aside.config import DEFAULT_CONFIG
        import copy
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["model"]["name"] = "anthropic/claude-haiku-4-5"
        from aside.daemon import Daemon
        with mock.patch("subprocess.Popen"):
            d = Daemon(config)
        return d

    @pytest.mark.asyncio
    async def test_get_model(self, daemon):
        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps({"action": "get_model"}).encode())
        reader.feed_eof()

        writer = mock.AsyncMock()
        writer.write = mock.Mock()
        writer.close = mock.Mock()
        writer.wait_closed = mock.AsyncMock()

        await daemon.handle_client(reader, writer)

        written = writer.write.call_args[0][0]
        data = json.loads(written.decode())
        assert data["model"] == "anthropic/claude-haiku-4-5"

    @pytest.mark.asyncio
    async def test_set_model(self, daemon):
        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps({"action": "set_model", "model": "gemini/gemini-2.5-pro"}).encode())
        reader.feed_eof()

        writer = mock.AsyncMock()
        writer.write = mock.Mock()
        writer.close = mock.Mock()
        writer.wait_closed = mock.AsyncMock()

        await daemon.handle_client(reader, writer)

        assert daemon.config["model"]["name"] == "gemini/gemini-2.5-pro"
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::TestDaemonModelActions -x -v`
Expected: FAIL (no `set_model`/`get_model` handling)

**Step 3: Add socket handlers to daemon.py**

In `handle_client`, add these elif branches (after the `toggle_tts` branch around line 422):

```python
            elif action == "get_model":
                model = self.config.get("model", {}).get("name", "")
                response = json.dumps({"model": model}).encode("utf-8")
                writer.write(response)
                await writer.drain()
                log.info("Socket: get_model -> %s", model)

            elif action == "set_model":
                new_model = msg.get("model", "")
                if new_model:
                    self.config.setdefault("model", {})["name"] = new_model
                    self.status.set_model(new_model)
                    log.info("Socket: set_model -> %s", new_model)
                else:
                    log.warning("Socket: set_model with empty model name")
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::TestDaemonModelActions -x -v`
Expected: PASS

**Step 5: Commit**

```
git add aside/daemon.py tests/test_cli.py
git commit -m "feat: add get_model and set_model daemon socket actions"
```

---

### Task 4: Create `aside/models.py` — model discovery module

**Files:**
- Create: `aside/models.py`
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
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

        # Should deduplicate: both "claude-sonnet-4-6" and "anthropic/claude-sonnet-4-6"
        # become "anthropic/claude-sonnet-4-6"
        assert result == {"anthropic": ["anthropic/claude-sonnet-4-6"]}

    def test_empty_when_no_keys(self):
        from aside.models import available_models

        with mock.patch("aside.models.available_providers", return_value=[]):
            result = available_models()
        assert result == {}
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_models.py -x -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Create `aside/models.py`**

```python
"""Model discovery — available models filtered by API key availability."""

from __future__ import annotations

import os
import re

from aside.keyring import _PROVIDER_TO_ENV, get_key as keyring_get_key

# Keyring provider name -> litellm.models_by_provider key.
_LITELLM_PROVIDERS: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "gemini",
    "groq": "groq",
    "mistral": "mistral",
    "cohere": "cohere_chat",
    "together": "together_ai",
    "deepseek": "deepseek",
}

# Models matching any of these patterns are not chat-completable.
_NON_CHAT_RE = re.compile(
    r"embed|image|tts|audio|whisper|dall-e|imagen|moderation|realtime",
    re.IGNORECASE,
)


def _get_registry() -> dict[str, set[str]]:
    """Return litellm.models_by_provider (import deferred)."""
    import litellm
    return litellm.models_by_provider


def available_providers() -> list[str]:
    """Return provider names that have an API key available."""
    result = []
    for provider, env_var in _PROVIDER_TO_ENV.items():
        if os.environ.get(env_var):
            result.append(provider)
        elif keyring_get_key(provider):
            result.append(provider)
    return result


def available_models() -> dict[str, list[str]]:
    """Return chat models grouped by provider, filtered to keyed providers.

    Each model name is normalized to ``provider/model`` format.
    """
    providers = available_providers()
    if not providers:
        return {}

    registry = _get_registry()
    result: dict[str, list[str]] = {}

    for provider in providers:
        litellm_key = _LITELLM_PROVIDERS.get(provider)
        if litellm_key is None:
            continue

        raw_models = registry.get(litellm_key, set())
        seen: set[str] = set()

        for name in raw_models:
            if _NON_CHAT_RE.search(name):
                continue

            # Normalize to provider/model
            if "/" not in name:
                name = f"{litellm_key}/{name}"

            if name not in seen:
                seen.add(name)

        if seen:
            result[provider] = sorted(seen)

    return result
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_models.py -x -v`
Expected: PASS

**Step 5: Commit**

```
git add aside/models.py tests/test_models.py
git commit -m "feat: add model discovery module (aside/models.py)"
```

---

### Task 5: Add `aside models` and `aside model set` CLI commands

**Files:**
- Modify: `aside/cli.py` (parser + handlers)
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

In `tests/test_cli.py`, add:

```python
class TestModelsCommand:
    def test_parse_models(self):
        parser = _build_parser()
        args = parser.parse_args(["models"])
        assert args.command == "models"

    def test_parse_model_set(self):
        parser = _build_parser()
        args = parser.parse_args(["model", "set", "gemini/gemini-2.5-pro"])
        assert args.command == "model"
        assert args.model_action == "set"
        assert args.name == "gemini/gemini-2.5-pro"

    def test_models_lists_grouped_output(self, capsys):
        fake_models = {
            "anthropic": ["anthropic/claude-haiku-4-5", "anthropic/claude-sonnet-4-6"],
            "gemini": ["gemini/gemini-2.5-pro"],
        }
        with mock.patch("aside.models.available_models", return_value=fake_models):
            with mock.patch("aside.cli._send_recv", return_value={"model": "anthropic/claude-haiku-4-5"}):
                from aside.cli import _cmd_models
                _cmd_models(mock.Mock())

        out = capsys.readouterr().out
        assert "anthropic" in out
        assert "* anthropic/claude-haiku-4-5" in out
        assert "  anthropic/claude-sonnet-4-6" in out
        assert "gemini" in out

    def test_model_set_sends_socket_message(self):
        with mock.patch("aside.cli._send") as mock_send:
            from aside.cli import _cmd_model
            args = mock.Mock()
            args.model_action = "set"
            args.name = "gemini/gemini-2.5-pro"
            _cmd_model(args)
            mock_send.assert_called_once_with({"action": "set_model", "model": "gemini/gemini-2.5-pro"})
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::TestModelsCommand -x -v`
Expected: FAIL

**Step 3: Add CLI commands to cli.py**

In `_build_parser`, add after the `get-key` parser (around line 148):

```python
    # aside models
    sub.add_parser("models", help="List available models (filtered by API keys)")

    # aside model set NAME
    model_cmd = sub.add_parser("model", help="Manage the active model")
    model_sub = model_cmd.add_subparsers(dest="model_action")
    model_sub.required = True
    model_set = model_sub.add_parser("set", help="Switch the active model (runtime)")
    model_set.add_argument("name", help="Model name (e.g. gemini/gemini-2.5-pro)")
```

Add handler functions:

```python
def _cmd_models(args: argparse.Namespace) -> None:
    """List available models grouped by provider."""
    import aside.models

    models = aside.models.available_models()
    if not models:
        print("No models available (no API keys found)")
        return

    # Try to get current model from daemon
    try:
        resp = _send_recv({"action": "get_model"})
        current = resp.get("model", "")
    except SystemExit:
        # Daemon not running, read from config
        cfg = load_config()
        current = cfg.get("model", {}).get("name", "")

    for provider in sorted(models):
        print(provider)
        for name in models[provider]:
            marker = "*" if name == current else " "
            print(f"  {marker} {name}")
        print()


def _cmd_model(args: argparse.Namespace) -> None:
    """Model subcommand dispatcher."""
    if args.model_action == "set":
        _send({"action": "set_model", "model": args.name})
        print(f"Model set to {args.name}")
```

Add to `_HANDLERS`:

```python
    "models": _cmd_models,
    "model": _cmd_model,
```

Update the import at top of cli.py to include `_send_recv`.

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py::TestModelsCommand -x -v`
Expected: PASS

**Step 5: Commit**

```
git add aside/cli.py tests/test_cli.py
git commit -m "feat: add 'aside models' and 'aside model set' CLI commands"
```

---

### Task 6: Full test suite + install

**Files:** None new — verification only.

**Step 1: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: All 248+ tests pass.

**Step 2: Build and install**

Run: `make dev`

**Step 3: Smoke test**

```bash
aside models
aside model set gemini/gemini-2.5-flash
aside status  # verify model changed
```

**Step 4: Commit any fixups, if needed**
