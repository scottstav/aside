"""Tests for aside.cli — argparse CLI entry point."""

from __future__ import annotations

import json
import socket
import os
from pathlib import Path
from unittest import mock

import pytest

from aside.cli import main, _send, _build_parser


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class TestArgumentParsing:
    """Verify argparse subcommand structure."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.parser = _build_parser()

    def test_query_basic(self):
        args = self.parser.parse_args(["query", "what time is it"])
        assert args.command == "query"
        assert args.text == "what time is it"
        assert args.conversation_id is None
        assert args.new is False

    def test_query_with_conversation_id(self):
        args = self.parser.parse_args(["query", "hello", "-c", "abc-123"])
        assert args.command == "query"
        assert args.text == "hello"
        assert args.conversation_id == "abc-123"

    def test_query_with_new_flag(self):
        args = self.parser.parse_args(["query", "hello", "--new"])
        assert args.command == "query"
        assert args.new is True

    def test_cancel(self):
        args = self.parser.parse_args(["cancel"])
        assert args.command == "cancel"

    def test_stop_tts(self):
        args = self.parser.parse_args(["stop-tts"])
        assert args.command == "stop-tts"

    def test_status(self):
        args = self.parser.parse_args(["status"])
        assert args.command == "status"

    def test_no_subcommand_exits(self):
        """Calling with no subcommand should cause an error."""
        with pytest.raises(SystemExit):
            self.parser.parse_args([])


# ---------------------------------------------------------------------------
# _send helper
# ---------------------------------------------------------------------------


class TestSend:
    """Test the _send helper that talks to the daemon socket."""

    def test_send_connects_and_writes(self, tmp_path):
        """_send should connect to the socket, send JSON, and close."""
        sock_path = tmp_path / "test.sock"

        # Create a listening socket
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)

        received = []

        def accept_one():
            conn, _ = server.accept()
            data = conn.recv(65536)
            received.append(data)
            conn.close()

        import threading
        t = threading.Thread(target=accept_one, daemon=True)
        t.start()

        with mock.patch("aside.cli.resolve_socket_path", return_value=sock_path):
            _send({"action": "cancel"})

        t.join(timeout=2)
        server.close()

        assert len(received) == 1
        msg = json.loads(received[0].decode("utf-8"))
        assert msg["action"] == "cancel"

    def test_send_daemon_not_running(self, tmp_path, capsys):
        """When the daemon socket doesn't exist, _send should print an error and exit."""
        sock_path = tmp_path / "nonexistent.sock"

        with mock.patch("aside.cli.resolve_socket_path", return_value=sock_path):
            with pytest.raises(SystemExit) as exc_info:
                _send({"action": "cancel"})

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not running" in captured.err.lower() or "not running" in captured.out.lower()


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------


class TestStatusCommand:
    """Test the status subcommand that reads status.json directly."""

    def test_status_prints_json(self, tmp_path, capsys):
        """status command should read and print status.json."""
        state_dir = tmp_path / "aside"
        state_dir.mkdir()
        status_data = {
            "status": "thinking",
            "model": "anthropic/claude-sonnet-4-6",
            "tool_name": "",
            "speak_enabled": False,
            "usage": {"month_cost": "$1.23", "last_query_cost": "$0.05", "total_tokens": 5000},
        }
        (state_dir / "status.json").write_text(json.dumps(status_data))

        cfg = {"status": {"signal": 12}}

        with mock.patch("aside.cli.load_config", return_value=cfg):
            with mock.patch("aside.cli.resolve_state_dir", return_value=state_dir):
                from aside.cli import _cmd_status
                _cmd_status(mock.MagicMock())

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "thinking"
        assert output["model"] == "anthropic/claude-sonnet-4-6"

    def test_status_missing_file(self, tmp_path, capsys):
        """When status.json doesn't exist, should print a message and exit 1."""
        state_dir = tmp_path / "aside"
        state_dir.mkdir()

        cfg = {"status": {"signal": 12}}

        with mock.patch("aside.cli.load_config", return_value=cfg):
            with mock.patch("aside.cli.resolve_state_dir", return_value=state_dir):
                from aside.cli import _cmd_status
                with pytest.raises(SystemExit) as exc_info:
                    _cmd_status(mock.MagicMock())

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Subcommand dispatch (integration)
# ---------------------------------------------------------------------------


class TestMainDispatch:
    """Verify that main() dispatches to the correct handler."""

    def test_query_sends_message(self, tmp_path):
        """aside query 'text' should send a query action to the socket."""
        with mock.patch("aside.cli._send") as mock_send:
            with mock.patch("sys.argv", ["aside", "query", "hello world"]):
                main()

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert msg["action"] == "query"
        assert msg["text"] == "hello world"
        assert "conversation_id" not in msg or msg["conversation_id"] is None

    def test_query_with_new_sends_sentinel(self, tmp_path):
        """aside query --new 'text' should send __new__ as conversation_id."""
        with mock.patch("aside.cli._send") as mock_send:
            with mock.patch("sys.argv", ["aside", "query", "--new", "hello"]):
                main()

        msg = mock_send.call_args[0][0]
        assert msg["conversation_id"] == "__new__"

    def test_query_with_conv_id(self):
        with mock.patch("aside.cli._send") as mock_send:
            with mock.patch("sys.argv", ["aside", "query", "-c", "conv-42", "hello"]):
                main()

        msg = mock_send.call_args[0][0]
        assert msg["conversation_id"] == "conv-42"

    def test_cancel_sends_message(self):
        with mock.patch("aside.cli._send") as mock_send:
            with mock.patch("sys.argv", ["aside", "cancel"]):
                main()

        msg = mock_send.call_args[0][0]
        assert msg["action"] == "cancel"

    def test_stop_tts_sends_message(self):
        with mock.patch("aside.cli._send") as mock_send:
            with mock.patch("sys.argv", ["aside", "stop-tts"]):
                main()

        msg = mock_send.call_args[0][0]
        assert msg["action"] == "stop_tts"
