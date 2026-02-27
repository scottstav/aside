"""Tests for aside.daemon — socket server, query dispatch, overlay config."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from aside.config import DEFAULT_CONFIG
from aside.daemon import Daemon, _write_overlay_config


# ---------------------------------------------------------------------------
# Minimal config fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_config(tmp_path):
    """Return a config dict with tmp paths so nothing touches real state."""
    import copy

    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["storage"]["conversations_dir"] = str(tmp_path / "conversations")
    cfg["_state_dir_override"] = str(tmp_path / "state")
    cfg["_config_dir_override"] = str(tmp_path / "config")
    return cfg


# ---------------------------------------------------------------------------
# Overlay config generation
# ---------------------------------------------------------------------------


class TestOverlayConfig:
    def test_write_overlay_config_creates_file(self, tmp_path, minimal_config):
        """The overlay config file should be written in KEY=VALUE format."""
        out = tmp_path / "config" / "aside" / "overlay.conf"
        _write_overlay_config(minimal_config["overlay"], out)

        assert out.exists()
        content = out.read_text()
        # Spot-check some expected keys
        assert "font=Sans 13" in content
        assert "width=600" in content
        assert "max_lines=40" in content

    def test_overlay_config_maps_color_keys(self, tmp_path, minimal_config):
        """Colors should be remapped: foreground->text_color, etc."""
        out = tmp_path / "overlay.conf"
        _write_overlay_config(minimal_config["overlay"], out)

        content = out.read_text()
        assert "text_color=#c0caf5ff" in content
        assert "border_color=#414868ff" in content
        assert "accent_color=#7aa2f7ff" in content
        assert "background=#1a1b26e6" in content
        # Original nested key names should NOT appear as top-level keys
        assert "\nforeground=" not in content
        assert "\nborder=" not in content

    def test_overlay_config_custom_values(self, tmp_path):
        """Custom overlay values should be written correctly."""
        overlay_cfg = {
            "font": "Mono 10",
            "width": 800,
            "max_lines": 20,
            "margin_top": 5,
            "padding_x": 10,
            "padding_y": 8,
            "corner_radius": 0,
            "border_width": 1,
            "accent_height": 2,
            "scroll_duration": 100,
            "fade_duration": 200,
            "colors": {
                "background": "#000000ff",
                "foreground": "#ffffffff",
                "border": "#333333ff",
                "accent": "#ff0000ff",
            },
        }
        out = tmp_path / "overlay.conf"
        _write_overlay_config(overlay_cfg, out)

        content = out.read_text()
        assert "font=Mono 10" in content
        assert "width=800" in content
        assert "text_color=#ffffffff" in content
        assert "accent_color=#ff0000ff" in content

    def test_overlay_config_creates_parent_dirs(self, tmp_path):
        """Parent directories should be created if they don't exist."""
        overlay_cfg = DEFAULT_CONFIG["overlay"]
        out = tmp_path / "deep" / "nested" / "overlay.conf"
        _write_overlay_config(overlay_cfg, out)
        assert out.exists()


# ---------------------------------------------------------------------------
# Daemon construction
# ---------------------------------------------------------------------------


class TestDaemonConstruction:
    def test_construct_with_minimal_config(self, minimal_config, tmp_path):
        """Daemon should initialise all components from config."""
        with mock.patch("aside.daemon.resolve_state_dir", return_value=tmp_path / "state"):
            with mock.patch("aside.daemon.resolve_conversations_dir", return_value=tmp_path / "conversations"):
                d = Daemon(minimal_config)

        assert d.config is minimal_config
        assert d.store is not None
        assert d.usage_log is not None
        assert d.status is not None
        assert d.voice is None  # voice disabled by default
        assert d.tts is None  # TTS disabled by default

    def test_construct_with_voice_disabled(self, minimal_config, tmp_path):
        """Voice should be None when config says disabled."""
        minimal_config["voice"]["enabled"] = False
        with mock.patch("aside.daemon.resolve_state_dir", return_value=tmp_path / "state"):
            with mock.patch("aside.daemon.resolve_conversations_dir", return_value=tmp_path / "conversations"):
                d = Daemon(minimal_config)
        assert d.voice is None

    def test_construct_with_voice_enabled_import_error(self, minimal_config, tmp_path):
        """Daemon should gracefully handle missing voice deps."""
        minimal_config["voice"]["enabled"] = True
        with mock.patch("aside.daemon.resolve_state_dir", return_value=tmp_path / "state"):
            with mock.patch("aside.daemon.resolve_conversations_dir", return_value=tmp_path / "conversations"):
                with mock.patch("aside.daemon.VoiceListener", side_effect=ImportError("no voice deps")):
                    d = Daemon(minimal_config)
        assert d.voice is None

    def test_construct_with_tts_enabled_import_error(self, minimal_config, tmp_path):
        """Daemon should handle missing TTS deps gracefully."""
        minimal_config["tts"]["enabled"] = True
        with mock.patch("aside.daemon.resolve_state_dir", return_value=tmp_path / "state"):
            with mock.patch("aside.daemon.resolve_conversations_dir", return_value=tmp_path / "conversations"):
                with mock.patch("aside.daemon.TTSPipeline", side_effect=ImportError("no tts")):
                    d = Daemon(minimal_config)
        assert d.tts is None


# ---------------------------------------------------------------------------
# Query dispatch
# ---------------------------------------------------------------------------


class TestQueryDispatch:
    def _make_daemon(self, config, tmp_path):
        """Helper to build a Daemon with mocked paths."""
        with mock.patch("aside.daemon.resolve_state_dir", return_value=tmp_path / "state"):
            with mock.patch("aside.daemon.resolve_conversations_dir", return_value=tmp_path / "conversations"):
                return Daemon(config)

    def test_start_query_spawns_thread(self, minimal_config, tmp_path):
        """start_query should launch a background thread that calls send_query."""
        d = self._make_daemon(minimal_config, tmp_path)

        with mock.patch("aside.daemon.send_query") as mock_sq:
            d.start_query("hello world")
            # Give the thread time to start
            time.sleep(0.1)

        mock_sq.assert_called_once()
        call_kwargs = mock_sq.call_args
        assert call_kwargs[1]["text"] == "hello world"

    def test_start_query_cancels_previous(self, minimal_config, tmp_path):
        """Starting a new query should cancel any existing one."""
        d = self._make_daemon(minimal_config, tmp_path)

        barrier = threading.Event()

        def slow_query(**kwargs):
            barrier.wait(timeout=5)

        with mock.patch("aside.daemon.send_query", side_effect=slow_query):
            d.start_query("first query")
            time.sleep(0.05)
            first_cancel = d._cancel_event

            d.start_query("second query")
            time.sleep(0.05)

        # First cancel event should be set
        assert first_cancel.is_set()
        barrier.set()  # Let threads finish

    def test_cancel_query_no_running(self, minimal_config, tmp_path):
        """cancel_query should not raise when no query is running."""
        d = self._make_daemon(minimal_config, tmp_path)
        d.cancel_query()  # Should not raise

    def test_cancel_query_sets_event(self, minimal_config, tmp_path):
        """cancel_query should set the cancel event."""
        d = self._make_daemon(minimal_config, tmp_path)

        barrier = threading.Event()

        def slow_query(**kwargs):
            barrier.wait(timeout=5)

        with mock.patch("aside.daemon.send_query", side_effect=slow_query):
            d.start_query("test")
            time.sleep(0.05)
            d.cancel_query()

        assert d._cancel_event is None or d._cancel_event.is_set()
        barrier.set()

    def test_start_query_passes_all_params(self, minimal_config, tmp_path):
        """All query parameters should be forwarded to send_query."""
        d = self._make_daemon(minimal_config, tmp_path)

        with mock.patch("aside.daemon.send_query") as mock_sq:
            d.start_query("test", conversation_id="conv123", image="abc", file="/tmp/f.txt")
            time.sleep(0.1)

        kwargs = mock_sq.call_args[1]
        assert kwargs["text"] == "test"
        assert kwargs["conversation_id"] == "conv123"
        assert kwargs["image"] == "abc"
        assert kwargs["file"] == "/tmp/f.txt"


# ---------------------------------------------------------------------------
# Command parsing (handle_client)
# ---------------------------------------------------------------------------


class TestCommandParsing:
    """Test the socket command handler dispatching."""

    def _make_daemon(self, config, tmp_path):
        with mock.patch("aside.daemon.resolve_state_dir", return_value=tmp_path / "state"):
            with mock.patch("aside.daemon.resolve_conversations_dir", return_value=tmp_path / "conversations"):
                return Daemon(config)

    def _run_command(self, daemon, cmd_dict):
        """Simulate sending a JSON command through the async handler."""
        data = json.dumps(cmd_dict).encode("utf-8") + b"\n"

        async def _do():
            reader = asyncio.StreamReader()
            reader.feed_data(data)
            reader.feed_eof()

            # Mock writer
            writer_transport = mock.MagicMock()
            writer_protocol = mock.MagicMock()
            writer = asyncio.StreamWriter(
                writer_transport, writer_protocol, reader, asyncio.get_event_loop()
            )
            # Mock wait_closed to be a coroutine
            writer.close = mock.MagicMock()
            writer.wait_closed = mock.AsyncMock()

            await daemon.handle_client(reader, writer)
            return writer

        return asyncio.get_event_loop().run_until_complete(_do())

    @pytest.fixture(autouse=True)
    def _event_loop(self):
        """Ensure an event loop exists for each test."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        yield loop
        loop.close()

    def test_query_command(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        with mock.patch.object(d, "start_query") as mock_sq:
            self._run_command(d, {
                "action": "query",
                "text": "what time is it?",
                "conversation_id": "abc123",
            })
        mock_sq.assert_called_once_with(
            "what time is it?",
            conversation_id="abc123",
            image=None,
            file=None,
        )

    def test_query_command_empty_text(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        with mock.patch.object(d, "start_query") as mock_sq:
            self._run_command(d, {"action": "query", "text": ""})
        mock_sq.assert_not_called()

    def test_cancel_command(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        with mock.patch.object(d, "cancel_query") as mock_cancel:
            self._run_command(d, {"action": "cancel"})
        mock_cancel.assert_called_once()

    def test_listen_command(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        # Voice is None (disabled), so listen should be a no-op but not crash
        self._run_command(d, {"action": "listen", "conversation_id": "conv1"})

    def test_listen_command_with_voice(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        d.voice = mock.MagicMock()
        self._run_command(d, {"action": "listen", "conversation_id": "conv1"})
        d.voice.request_listen.assert_called_once_with(conversation_id="conv1")

    def test_mute_command(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        d.voice = mock.MagicMock()
        self._run_command(d, {"action": "mute"})
        d.voice.set_muted.assert_called_once_with(True)

    def test_unmute_command(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        d.voice = mock.MagicMock()
        self._run_command(d, {"action": "unmute"})
        d.voice.set_muted.assert_called_once_with(False)

    def test_stop_tts_with_tts(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        d.tts = mock.MagicMock()
        self._run_command(d, {"action": "stop_tts"})
        d.tts.stop.assert_called_once()

    def test_stop_tts_without_tts(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        # tts is None; should not crash
        self._run_command(d, {"action": "stop_tts"})

    def test_toggle_mute_returns_state(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        d.voice = mock.MagicMock()
        d._muted = False
        writer = self._run_command(d, {"action": "toggle-mute"})
        # Should have toggled mute and written response
        d.voice.set_muted.assert_called_once_with(True)

    def test_unknown_action_does_not_crash(self, minimal_config, tmp_path):
        d = self._make_daemon(minimal_config, tmp_path)
        # Should log a warning but not raise
        self._run_command(d, {"action": "nonexistent"})

    def test_invalid_json_does_not_crash(self, minimal_config, tmp_path):
        """Malformed JSON should be handled gracefully."""
        d = self._make_daemon(minimal_config, tmp_path)
        data = b"not valid json\n"

        async def _do():
            reader = asyncio.StreamReader()
            reader.feed_data(data)
            reader.feed_eof()
            writer = mock.MagicMock()
            writer.close = mock.MagicMock()
            writer.wait_closed = mock.AsyncMock()
            await d.handle_client(reader, writer)

        asyncio.get_event_loop().run_until_complete(_do())


# ---------------------------------------------------------------------------
# Socket server integration
# ---------------------------------------------------------------------------


class TestSocketServer:
    """Test the actual Unix socket server start/stop."""

    @pytest.fixture
    def sock_path(self, tmp_path):
        return tmp_path / "test.sock"

    def test_socket_server_accepts_connection(self, minimal_config, tmp_path, sock_path):
        """The socket server should accept a connection and process a command."""
        import socket

        with mock.patch("aside.daemon.resolve_state_dir", return_value=tmp_path / "state"):
            with mock.patch("aside.daemon.resolve_conversations_dir", return_value=tmp_path / "conversations"):
                d = Daemon(minimal_config)

        # Run server in background
        async def run_server():
            server = await asyncio.start_unix_server(
                d.handle_client,
                path=str(sock_path),
            )
            async with server:
                # Accept one connection then stop
                await asyncio.sleep(0.3)
                server.close()

        server_thread = threading.Thread(
            target=lambda: asyncio.run(run_server()),
            daemon=True,
        )
        server_thread.start()
        time.sleep(0.1)  # Let server start

        # Connect and send a cancel command
        with mock.patch.object(d, "cancel_query") as mock_cancel:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(sock_path))
            sock.sendall(json.dumps({"action": "cancel"}).encode("utf-8") + b"\n")
            sock.close()
            time.sleep(0.1)

        mock_cancel.assert_called_once()
        server_thread.join(timeout=2)
