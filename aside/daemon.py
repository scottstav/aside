"""Daemon — socket server, query dispatch, and orchestration.

The main long-running process that ties all aside components together:
socket server, conversation store, query pipeline, optional voice and TTS.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path

from aside.config import (
    load_config,
    resolve_conversations_dir,
    resolve_socket_path,
    resolve_state_dir,
)
from aside.plugins import load_tools
from aside.query import NEW_CONVERSATION, send_query
from aside.state import ConversationStore, StatusState, UsageLog

log = logging.getLogger("aside")

# ---------------------------------------------------------------------------
# API key caching — survive daemon restarts when env vars aren't re-set
# ---------------------------------------------------------------------------

# Env vars that may carry LLM API keys (LiteLLM convention).
_API_KEY_VARS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "TOGETHER_API_KEY",
    "DEEPSEEK_API_KEY",
]


def _api_key_cache_path() -> Path:
    """Return path to the runtime API key cache (tmpfs, lost on reboot)."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(runtime_dir) / "aside-api-keys"


def _cache_api_keys() -> None:
    """Persist current API key env vars to a runtime cache file.

    Only writes keys that are actually set.  The file is mode 0600 on tmpfs
    (``/run/user/$UID``), so it's user-only and lost on reboot.
    """
    keys = {k: os.environ[k] for k in _API_KEY_VARS if k in os.environ}
    if not keys:
        return
    cache = _api_key_cache_path()
    try:
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(keys))
        tmp.chmod(0o600)
        tmp.rename(cache)
        log.info("Cached %d API key(s) to %s", len(keys), cache)
    except OSError:
        pass  # non-fatal


def _restore_api_keys() -> None:
    """Restore API keys from runtime cache into env vars if missing.

    Only sets vars that aren't already in the environment, so explicit env
    always wins.
    """
    cache = _api_key_cache_path()
    if not cache.exists():
        return
    try:
        keys = json.loads(cache.read_text())
        restored = 0
        for k, v in keys.items():
            if k not in os.environ:
                os.environ[k] = v
                restored += 1
        if restored:
            log.info("Restored %d API key(s) from runtime cache", restored)
    except (OSError, json.JSONDecodeError):
        pass  # non-fatal


# Try to import optional heavy dependencies.  These are kept at module level
# so tests can mock them easily, but failures are deferred to __init__.
try:
    from aside.tts import TTSPipeline
except ImportError:
    TTSPipeline = None  # type: ignore[misc,assignment]

try:
    from aside.voice.listener import capture_one_shot
except ImportError:
    capture_one_shot = None  # type: ignore[misc,assignment]


# ---------------------------------------------------------------------------
# Overlay config writer
# ---------------------------------------------------------------------------

# Mapping from overlay.colors sub-keys to the KEY names the C overlay expects.
_COLOR_KEY_MAP = {
    "background": "background",
    "foreground": "text_color",
    "border": "border_color",
    "accent": "accent_color",
}

# Top-level overlay keys (non-color) written as-is.
_OVERLAY_SCALAR_KEYS = [
    "font",
    "width",
    "max_lines",
    "margin_top",
    "padding_x",
    "padding_y",
    "corner_radius",
    "border_width",
    "accent_height",
    "scroll_duration",
    "fade_duration",
]


def _write_overlay_config(overlay_cfg: dict, path: Path) -> None:
    """Write ``overlay.conf`` in KEY=VALUE format for the C overlay.

    Scalar keys are written directly.  The ``colors`` sub-dict is remapped:
    ``foreground`` -> ``text_color``, ``border`` -> ``border_color``,
    ``accent`` -> ``accent_color``, ``background`` stays as-is.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for key in _OVERLAY_SCALAR_KEYS:
        if key in overlay_cfg:
            lines.append(f"{key}={overlay_cfg[key]}")

    colors = overlay_cfg.get("colors", {})
    for src_key, dest_key in _COLOR_KEY_MAP.items():
        if src_key in colors:
            lines.append(f"{dest_key}={colors[src_key]}")

    path.write_text("\n".join(lines) + "\n")
    log.info("Wrote overlay config to %s", path)


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------


class Daemon:
    """Main daemon: socket server, query dispatch, and component orchestration.

    Parameters
    ----------
    config:
        Full config dict (from ``load_config``).
    """

    def __init__(self, config: dict) -> None:
        self.config = config

        # Resolve directories
        state_dir = resolve_state_dir(config)
        conv_dir = resolve_conversations_dir(config)

        # Core state
        self.store = ConversationStore(conv_dir)
        self.usage_log = UsageLog(state_dir / "usage.jsonl")
        self.status = StatusState(
            state_dir,
            signal_num=config.get("status", {}).get("signal", 12),
            usage_log_path=state_dir / "usage.jsonl",
            model=config.get("model", {}).get("name", "anthropic/claude-sonnet-4-6"),
        )

        # Built-in tools directory (alongside this module)
        built_in_tools_dir = Path(__file__).parent / "tools"
        plugin_dirs = [Path(d) for d in config.get("plugins", {}).get("dirs", [])]
        self.tools_dirs: list[Path] = [built_in_tools_dir] + plugin_dirs
        self._tools: list[dict] | None = None  # Lazy-loaded

        # Optional TTS
        self.tts = None
        tts_cfg = config.get("tts", {})
        if tts_cfg.get("enabled", False):
            try:
                if TTSPipeline is None:
                    raise ImportError("TTSPipeline not available")
                self.tts = TTSPipeline(
                    model=tts_cfg.get("model", "af_heart"),
                    speed=tts_cfg.get("speed", 1.0),
                    lang=tts_cfg.get("lang", "a"),
                )
                log.info("TTS pipeline initialised")
            except (ImportError, Exception):
                log.warning("TTS deps not installed — TTS disabled", exc_info=True)
                self.tts = None

        # Query cancel state
        self._cancel_event: threading.Event | None = None
        self._cancel_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Tool loading (lazy)
    # ------------------------------------------------------------------

    def _get_tools(self) -> list[dict]:
        """Load tool definitions on first use."""
        if self._tools is None:
            self._tools = load_tools(self.tools_dirs)
        return self._tools

    # ------------------------------------------------------------------
    # Query dispatch
    # ------------------------------------------------------------------

    def start_query(
        self,
        text: str,
        conversation_id=None,
        image: str | None = None,
        file: str | None = None,
    ) -> None:
        """Spawn a query in a background thread.

        Cancels any existing running query first.
        """
        cancel_event = threading.Event()
        with self._cancel_lock:
            if self._cancel_event is not None:
                self._cancel_event.set()
            self._cancel_event = cancel_event

        def _run():
            try:
                send_query(
                    text=text,
                    conversation_id=conversation_id,
                    config=self.config,
                    store=self.store,
                    status=self.status,
                    usage_log=self.usage_log,
                    cancel_event=cancel_event,
                    image=image,
                    file=file,
                    tts=self.tts,
                    plugin_dirs=self.tools_dirs,
                    tools=self._get_tools(),
                )
            except Exception:
                log.exception("Query thread error")
            finally:
                with self._cancel_lock:
                    if self._cancel_event is cancel_event:
                        self._cancel_event = None

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        conv_label = (
            "new"
            if conversation_id is NEW_CONVERSATION
            else (conversation_id or "auto")
        )
        log.info("Query thread started (conv=%s)", conv_label)

    def cancel_query(self) -> None:
        """Cancel the currently running query."""
        with self._cancel_lock:
            if self._cancel_event is not None:
                self._cancel_event.set()
                log.info("Query cancelled")
            else:
                log.info("No query to cancel")

    # ------------------------------------------------------------------
    # Socket handler
    # ------------------------------------------------------------------

    async def handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Process a single JSON command from a socket client.

        Commands are newline-delimited JSON.  Each connection sends one
        command and then closes.
        """
        try:
            data = await reader.read(65536)
            if not data:
                return

            msg = json.loads(data.decode("utf-8"))
            action = msg.get("action")

            if action == "query":
                if msg.get("mic"):
                    # One-shot voice capture in a thread (blocking call)
                    raw_conv = msg.get("conversation_id")
                    if raw_conv == "__new__":
                        conv_id = NEW_CONVERSATION
                    else:
                        conv_id = raw_conv

                    def _mic_capture():
                        try:
                            if capture_one_shot is None:
                                log.warning("Voice deps not installed -- mic capture unavailable")
                                return
                            text = capture_one_shot(self.config.get("voice", {}))
                            if text:
                                self.start_query(text, conversation_id=conv_id)
                            else:
                                log.info("Mic capture returned empty, no query started")
                        except Exception:
                            log.exception("Mic capture error")

                    threading.Thread(target=_mic_capture, daemon=True).start()
                    log.info("Socket: mic capture started (conv=%s)", raw_conv or "auto")
                else:
                    text = msg.get("text", "").strip()
                    if not text:
                        log.warning("Socket: empty query text")
                    else:
                        raw_conv = msg.get("conversation_id")
                        if raw_conv == "__new__":
                            conv_id = NEW_CONVERSATION
                        else:
                            conv_id = raw_conv
                        self.start_query(
                            text,
                            conversation_id=conv_id,
                            image=msg.get("image"),
                            file=msg.get("file"),
                        )
                        log.info("Socket: query (conv=%s)", raw_conv or "auto")

            elif action == "cancel":
                self.cancel_query()
                log.info("Socket: cancel")

            elif action == "stop_tts":
                if self.tts is not None:
                    self.tts.stop()
                    log.info("Socket: stop_tts")
                else:
                    log.info("Socket: stop_tts (no TTS active)")

                # Update status bar
                with self._cancel_lock:
                    query_active = self._cancel_event is not None
                if query_active:
                    self.status.set_status("thinking")
                else:
                    self.status.set_status("idle")

            else:
                log.warning("Socket: unknown action %r", action)

        except json.JSONDecodeError as e:
            log.error("Socket: invalid JSON: %s", e)
        except Exception:
            log.exception("Socket: error handling client")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the daemon: write overlay config, start socket server."""
        # Ensure state directories exist
        state_dir = resolve_state_dir(self.config)
        state_dir.mkdir(parents=True, exist_ok=True)

        # Write overlay config
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            config_dir = Path(xdg_config) / "aside"
        else:
            config_dir = Path.home() / ".config" / "aside"
        overlay_conf = config_dir / "overlay.conf"
        _write_overlay_config(self.config.get("overlay", {}), overlay_conf)

        # Run the socket server on the main thread (asyncio)
        asyncio.run(self._run_socket_server())

    async def _run_socket_server(self) -> None:
        """Start the asyncio Unix socket server and serve forever."""
        sock_path = resolve_socket_path("aside.sock")

        # Clean up stale socket
        try:
            os.unlink(sock_path)
        except FileNotFoundError:
            pass

        server = await asyncio.start_unix_server(
            self.handle_client,
            path=str(sock_path),
        )
        os.chmod(str(sock_path), 0o600)
        log.info("Socket server listening on %s", sock_path)

        async with server:
            await server.serve_forever()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


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


if __name__ == "__main__":
    main()
