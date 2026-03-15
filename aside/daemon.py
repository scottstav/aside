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
import time
from pathlib import Path

from aside.config import (
    load_config,
    resolve_archive_dir,
    resolve_conversations_dir,
    resolve_socket_path,
    resolve_state_dir,
)
from aside.plugins import load_tools
from aside.query import NEW_CONVERSATION, ContextWindowFull, send_query
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


try:
    from aside.tts import TTSPipeline
except ImportError:
    TTSPipeline = None  # type: ignore[misc,assignment]

try:
    from aside.voice.audio import AudioPipeline  # noqa: F401 — forces numpy/sounddevice import
    from aside.voice.listener import capture_one_shot
except (ImportError, RuntimeError):
    capture_one_shot = None  # type: ignore[misc,assignment]


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
        archive_dir = resolve_archive_dir(config)

        # Core state
        self.store = ConversationStore(conv_dir, archive_dir=archive_dir)
        self.usage_log = UsageLog(state_dir / "usage.jsonl")
        self.status = StatusState(
            state_dir,
            signal_num=config.get("status", {}).get("signal", 12),
            usage_log_path=state_dir / "usage.jsonl",
            model=config.get("model", {}).get("name", "anthropic/claude-sonnet-4-6"),
            speak_enabled=config.get("tts", {}).get("enabled", False),
        )

        # Built-in tools directory (alongside this module)
        built_in_tools_dir = Path(__file__).parent / "tools"
        # User-configured plugin directories
        plugin_dirs = [Path(d).expanduser() for d in config.get("tools", {}).get("dirs", [])]
        self.tools_dirs: list[Path] = [built_in_tools_dir] + plugin_dirs
        self._tools: list[dict] | None = None  # Lazy-loaded

        # Optional TTS — always try to initialise so toggle-tts works.
        # The config "enabled" key controls the default speak_enabled state.
        self.tts = None
        tts_cfg = config.get("tts", {})
        try:
            if TTSPipeline is None:
                raise ImportError("piper-tts not installed")
            self.tts = TTSPipeline(
                model=tts_cfg.get("model", ""),
                speed=tts_cfg.get("speed", 1.0),
            )
            log.info("TTS pipeline initialised")
        except ImportError:
            log.info("TTS not available — piper-tts not installed")
        except Exception:
            log.exception("TTS init failed")
            self.tts = None

        # Last conversation ID (in-memory, authoritative)
        self.last_conv_id: str | None = self.store.resolve_last()

        # Query cancel state
        self._cancel_event: threading.Event | None = None
        self._cancel_lock = threading.Lock()
        # Mic capture cancel state (separate from query cancel)
        self._mic_cancel: threading.Event | None = None

    # ------------------------------------------------------------------
    # Tool loading (lazy)
    # ------------------------------------------------------------------

    def _get_tools(self) -> list[dict]:
        """Load tool definitions on first use."""
        if self._tools is None:
            self._tools = load_tools(self.tools_dirs)
        return self._tools

    def _resolve_conv(self, raw: str | None):
        """Resolve a conversation_id from a socket message.

        - ``"__new__"`` → NEW_CONVERSATION (force new)
        - ``"uuid-string"`` → that specific id
        - ``None`` → last_conv_id from memory (continues last convo)
        """
        if raw == "__new__":
            return NEW_CONVERSATION
        if raw:
            return raw
        return self.last_conv_id

    # ------------------------------------------------------------------
    # Query dispatch
    # ------------------------------------------------------------------

    def start_query(
        self,
        text: str,
        conversation_id=None,
        image: str | None = None,
        file: str | None = None,
        from_mic: bool = False,
    ) -> None:
        """Spawn a query in a background thread.

        Cancels any existing running query first.
        When *from_mic* is True, the overlay already shows the user's
        transcribed text in thinking mode — the query pipeline will defer
        the overlay "open" until the first LLM response chunk arrives.
        """

        cancel_event = threading.Event()
        with self._cancel_lock:
            if self._cancel_event is not None:
                self._cancel_event.set()
            self._cancel_event = cancel_event
        # Stop TTS from any previous query immediately
        if self.tts is not None:
            self.tts.stop()

        def _run():
            try:
                result_id = send_query(
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
                    from_mic=from_mic,
                )
                if result_id:
                    self.last_conv_id = result_id
            except ContextWindowFull:
                log.info("Context window full — retrying with new conversation")
                try:
                    result_id = send_query(
                        text=text,
                        conversation_id=NEW_CONVERSATION,
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
                        from_mic=from_mic,
                    )
                    if result_id:
                        self.last_conv_id = result_id
                except Exception:
                    log.exception("Retry with new conversation failed")
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
        """Cancel the currently running query, mic capture, and TTS."""
        with self._cancel_lock:
            if self._cancel_event is not None:
                self._cancel_event.set()
                log.info("Query cancelled")
            else:
                log.info("No query to cancel")
            if self._mic_cancel is not None:
                self._mic_cancel.set()
        if self.tts is not None:
            self.tts.stop()

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
                    if capture_one_shot is None:
                        from aside.query import _connect_overlay, _overlay_send, _overlay_close
                        sock = _connect_overlay()
                        _overlay_send(sock, {"cmd": "open", "mode": "user"})
                        _overlay_send(sock, {"cmd": "replace", "data": "STT not installed. Run: sudo aside enable-stt"})
                        await asyncio.sleep(3)
                        _overlay_send(sock, {"cmd": "done"})
                        _overlay_close(sock)
                        log.warning("STT not installed — mic query rejected")
                        return

                    # Cancel any running query/TTS/mic before starting
                    self.cancel_query()

                    # Create a cancel event for this mic capture
                    mic_cancel = threading.Event()
                    with self._cancel_lock:
                        self._mic_cancel = mic_cancel

                    # One-shot voice capture in a thread (blocking call)
                    conv_id = self._resolve_conv(msg.get("conversation_id"))

                    def _mic_capture(cancel=mic_cancel):
                        from aside.query import _connect_overlay, _overlay_send, _overlay_close

                        overlay_sock = None
                        try:
                            log.debug("mic: connecting to overlay socket")
                            overlay_sock = _connect_overlay()
                            log.debug("mic: overlay socket=%s", overlay_sock)
                            _overlay_send(overlay_sock, {
                                "cmd": "open",
                                "mode": "user",
                                "conv_id": "" if conv_id is NEW_CONVERSATION else (conv_id or ""),
                            })
                            log.debug("mic: sent open+listening to overlay")
                            _overlay_send(overlay_sock, {"cmd": "listening"})

                            def on_interim(text):
                                log.debug("mic: on_interim called: %r", text[:80] if text else "")
                                _overlay_send(overlay_sock, {
                                    "cmd": "replace",
                                    "data": text,
                                })

                            def on_audio_level(level):
                                _overlay_send(overlay_sock, {
                                    "cmd": "audio_level",
                                    "data": level,
                                })

                            def on_capture_end():
                                log.debug("mic: on_capture_end — sending thinking to overlay")
                                _overlay_send(overlay_sock, {"cmd": "thinking"})

                            log.debug("mic: calling capture_one_shot")
                            text = capture_one_shot(
                                self.config.get("voice", {}),
                                on_interim=on_interim,
                                on_audio_level=on_audio_level,
                                on_capture_end=on_capture_end,
                                cancel_event=cancel,
                            )
                            log.debug("mic: capture_one_shot returned: %r", text[:80] if text else "")

                            if text:
                                log.debug("mic: showing final transcription, starting query")
                                # Show the final transcription, then re-start thinking dots
                                # so user sees dots while waiting for LLM response.
                                _overlay_send(overlay_sock, {
                                    "cmd": "replace",
                                    "data": text,
                                })
                                _overlay_send(overlay_sock, {"cmd": "thinking"})
                                _overlay_close(overlay_sock)
                                self.start_query(text, conversation_id=conv_id, from_mic=True)
                            else:
                                log.info("Mic capture returned empty, no query started")
                                _overlay_close(overlay_sock)
                                clear_sock = _connect_overlay()
                                _overlay_send(clear_sock, {"cmd": "clear"})
                                _overlay_close(clear_sock)
                        except Exception as exc:
                            log.exception("Mic capture error")
                            try:
                                err_sock = _connect_overlay()
                                _overlay_send(err_sock, {
                                    "cmd": "open",
                                    "mode": "user",
                                })
                                _overlay_send(err_sock, {
                                    "cmd": "replace",
                                    "data": f"Mic error: {exc}",
                                })
                                time.sleep(2)
                                _overlay_close(err_sock)
                                clear_sock = _connect_overlay()
                                _overlay_send(clear_sock, {"cmd": "clear"})
                                _overlay_close(clear_sock)
                            except Exception:
                                log.debug("Failed to show mic error in overlay")

                    threading.Thread(target=_mic_capture, daemon=True).start()
                    log.info("Socket: mic capture started (conv=%s)", conv_id or "auto")
                else:
                    text = msg.get("text", "").strip()
                    if not text:
                        log.warning("Socket: empty query text")
                    else:
                        conv_id = self._resolve_conv(msg.get("conversation_id"))
                        self.start_query(
                            text,
                            conversation_id=conv_id,
                            image=msg.get("image"),
                            file=msg.get("file"),
                        )
                        log.info("Socket: query (conv=%s)", conv_id or "auto")

            elif action == "cancel":
                self.cancel_query()
                # Dismiss the overlay — since this is an explicit cancel,
                # no new operation is taking over.
                try:
                    from aside.query import _connect_overlay, _overlay_send, _overlay_close
                    sock = _connect_overlay()
                    _overlay_send(sock, {"cmd": "clear"})
                    _overlay_close(sock)
                except Exception:
                    pass
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

            elif action == "toggle_tts":
                new_val = not self.status.speak_enabled
                self.status.speak_enabled = new_val
                log.info("Socket: toggle_tts -> %s", new_val)

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
        """Start the daemon: start socket server."""
        # Ensure state directories exist
        state_dir = resolve_state_dir(self.config)
        state_dir.mkdir(parents=True, exist_ok=True)

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
    import sys
    debug = os.environ.get("ASIDE_DEBUG", "").lower() in ("1", "true", "yes") \
            or "--debug" in sys.argv
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if debug:
        log.info("Debug logging enabled")
    _restore_api_keys()

    from aside.keyring import load_keyring_keys
    load_keyring_keys()

    _cache_api_keys()
    config = load_config()
    Daemon(config).run()


if __name__ == "__main__":
    main()
