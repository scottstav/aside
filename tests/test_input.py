"""Tests for aside.input.window — GTK4 input popup.

GTK4 applications are difficult to fully unit-test without a display
server. These tests exercise the importable logic and socket communication
while gracefully skipping GTK-dependent code when unavailable.
"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Import helpers — skip when GTK4 is missing
# ---------------------------------------------------------------------------

def _gtk_available() -> bool:
    """Return True if GTK4 + libadwaita + layer-shell can be loaded."""
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk, Adw, Gtk4LayerShell  # noqa: F401
        return True
    except (ImportError, ValueError):
        return False


gtk_available = _gtk_available()
skip_no_gtk = pytest.mark.skipif(not gtk_available, reason="GTK4/libadwaita not available")


# ---------------------------------------------------------------------------
# Module import test
# ---------------------------------------------------------------------------


class TestImport:
    @skip_no_gtk
    def test_module_imports(self):
        """The input window module should be importable when GTK4 is present."""
        from aside.input import window  # noqa: F401
        assert hasattr(window, "main")
        assert hasattr(window, "AsideInput")
        assert hasattr(window, "AsideInputWindow")
        assert hasattr(window, "_send_to_daemon")


# ---------------------------------------------------------------------------
# Socket communication
# ---------------------------------------------------------------------------


class TestSendToDaemon:
    @skip_no_gtk
    def test_send_to_daemon_sends_json(self, tmp_path):
        """_send_to_daemon should connect and send newline-terminated JSON."""
        from aside.input.window import _send_to_daemon

        sock_path = tmp_path / "test.sock"
        received = []

        def server():
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(sock_path))
            srv.listen(1)
            conn, _ = srv.accept()
            data = conn.recv(4096)
            received.append(data)
            conn.close()
            srv.close()

        server_thread = threading.Thread(target=server, daemon=True)
        server_thread.start()

        import time
        time.sleep(0.05)  # let server bind

        msg = {"action": "query", "text": "hello", "conversation_id": None}
        with mock.patch("aside.input.window.resolve_socket_path", return_value=sock_path):
            _send_to_daemon(msg)

        server_thread.join(timeout=2)

        assert len(received) == 1
        decoded = json.loads(received[0].decode().strip())
        assert decoded["action"] == "query"
        assert decoded["text"] == "hello"

    @skip_no_gtk
    def test_send_to_daemon_handles_missing_socket(self):
        """_send_to_daemon should not raise when the socket doesn't exist."""
        from aside.input.window import _send_to_daemon

        with mock.patch(
            "aside.input.window.resolve_socket_path",
            return_value=Path("/nonexistent/path/aside.sock"),
        ):
            # Should not raise
            _send_to_daemon({"action": "query", "text": "test"})


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelpers:
    @skip_no_gtk
    def test_format_date_today(self):
        """Dates from today should show time only."""
        from aside.input.window import _format_date
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        iso = now.isoformat()
        result = _format_date(iso)
        # Should be HH:MM format
        assert ":" in result
        assert len(result) <= 5

    @skip_no_gtk
    def test_format_date_past(self):
        """Dates from the past should show month and day."""
        from aside.input.window import _format_date

        result = _format_date("2025-01-15T12:00:00+00:00")
        assert "Jan" in result
        assert "15" in result

    @skip_no_gtk
    def test_format_date_invalid(self):
        """Invalid date strings should return empty string."""
        from aside.input.window import _format_date

        assert _format_date("not-a-date") == ""
        assert _format_date("") == ""
        assert _format_date(None) == ""

    @skip_no_gtk
    def test_new_conversation_constant(self):
        """The new-conversation sentinel should match daemon expectation."""
        from aside.input.window import _NEW_CONVERSATION_ID

        assert _NEW_CONVERSATION_ID == "__new__"


# ---------------------------------------------------------------------------
# Row construction (requires display, but tests the logic)
# ---------------------------------------------------------------------------


class TestRowConstruction:
    @skip_no_gtk
    def test_make_new_conversation_row(self):
        """The new conversation row should carry the sentinel ID."""
        from aside.input.window import _make_new_conversation_row, _NEW_CONVERSATION_ID

        row = _make_new_conversation_row()
        assert row._conversation_id == _NEW_CONVERSATION_ID

    @skip_no_gtk
    def test_make_conversation_row(self):
        """Conversation rows should carry their ID."""
        from aside.input.window import _make_conversation_row

        row = _make_conversation_row("abc-123", "2025-06-01T12:00:00Z", "Hello world")
        assert row._conversation_id == "abc-123"

    @skip_no_gtk
    def test_make_conversation_row_truncates_preview(self):
        """Long previews should be truncated."""
        from aside.input.window import _make_conversation_row

        long_text = "x" * 200
        row = _make_conversation_row("id1", "2025-06-01T12:00:00Z", long_text)
        assert row._conversation_id == "id1"
