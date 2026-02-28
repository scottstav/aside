"""Tests for aside.cli — argparse CLI entry point."""

from __future__ import annotations

import asyncio
import json
import socket
import os
from pathlib import Path
from unittest import mock

import pytest

from aside.cli import main, _send, _send_recv, _build_parser, _cmd_ls, _cmd_show, _cmd_open, _cmd_rm, _cmd_reply, _cmd_query, _cmd_set_key, _cmd_get_key, _cmd_models, _cmd_model


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

    def test_query_mic(self):
        args = self.parser.parse_args(["query", "--mic"])
        assert args.command == "query"
        assert args.mic is True
        assert args.text is None

    def test_query_mic_with_conversation_id(self):
        args = self.parser.parse_args(["query", "--mic", "-c", "conv-42"])
        assert args.command == "query"
        assert args.mic is True
        assert args.conversation_id == "conv-42"
        assert args.text is None

    def test_query_mic_with_new_flag(self):
        args = self.parser.parse_args(["query", "--mic", "--new"])
        assert args.command == "query"
        assert args.mic is True
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

    def test_ls(self):
        args = self.parser.parse_args(["ls"])
        assert args.command == "ls"

    def test_ls_with_limit(self):
        args = self.parser.parse_args(["ls", "-n", "10"])
        assert args.command == "ls"
        assert args.limit == 10

    def test_ls_default_limit(self):
        args = self.parser.parse_args(["ls"])
        assert args.limit == 20

    def test_show(self):
        args = self.parser.parse_args(["show", "abc-123"])
        assert args.command == "show"
        assert args.conversation_id == "abc-123"

    def test_open(self):
        args = self.parser.parse_args(["open", "abc-123"])
        assert args.command == "open"
        assert args.conversation_id == "abc-123"

    def test_rm(self):
        args = self.parser.parse_args(["rm", "abc-123"])
        assert args.command == "rm"
        assert args.conversation_id == "abc-123"

    def test_reply_basic(self):
        args = self.parser.parse_args(["reply", "conv-42"])
        assert args.command == "reply"
        assert args.conversation_id == "conv-42"
        assert args.text is None
        assert args.gui is False
        assert args.mic is False

    def test_reply_with_text(self):
        args = self.parser.parse_args(["reply", "conv-42", "follow up question"])
        assert args.command == "reply"
        assert args.conversation_id == "conv-42"
        assert args.text == "follow up question"

    def test_reply_with_gui(self):
        args = self.parser.parse_args(["reply", "conv-42", "--gui"])
        assert args.command == "reply"
        assert args.conversation_id == "conv-42"
        assert args.gui is True
        assert args.text is None

    def test_reply_with_mic(self):
        args = self.parser.parse_args(["reply", "conv-42", "--mic"])
        assert args.command == "reply"
        assert args.conversation_id == "conv-42"
        assert args.mic is True
        assert args.text is None

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


# ---------------------------------------------------------------------------
# ls command
# ---------------------------------------------------------------------------


class TestLsCommand:
    """Test the ls subcommand that lists recent conversations."""

    def _make_conv(self, conv_dir, conv_id, created, messages):
        """Write a conversation JSON file."""
        data = {"id": conv_id, "created": created, "messages": messages}
        (conv_dir / f"{conv_id}.json").write_text(json.dumps(data))

    def test_ls_lists_conversations(self, tmp_path, capsys):
        """ls should print one line per conversation."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "aaaa-1111", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": "What is the weather?"},
            {"role": "assistant", "content": "It is sunny."},
        ])
        self._make_conv(conv_dir, "bbbb-2222", "2026-02-27T09:00:00+00:00", [
            {"role": "user", "content": "Tell me a joke"},
        ])

        args = mock.MagicMock()
        args.limit = 20

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_ls(args)

        captured = capsys.readouterr()
        lines = [l for l in captured.out.strip().splitlines() if l.strip()]
        assert len(lines) == 2

        # Both conversation IDs should appear (first 7 chars)
        assert "aaaa-11" in captured.out
        assert "bbbb-22" in captured.out

    def test_ls_shows_first_user_message(self, tmp_path, capsys):
        """ls should show the first user message preview."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "cccc-3333", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": "How do I bake a cake?"},
        ])

        args = mock.MagicMock()
        args.limit = 20

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_ls(args)

        captured = capsys.readouterr()
        assert "How do I bake a cake?" in captured.out

    def test_ls_truncates_long_message(self, tmp_path, capsys):
        """Messages longer than 60 chars should be truncated."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        long_msg = "A" * 80
        self._make_conv(conv_dir, "dddd-4444", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": long_msg},
        ])

        args = mock.MagicMock()
        args.limit = 20

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_ls(args)

        captured = capsys.readouterr()
        # Should not contain the full 80-char message
        assert long_msg not in captured.out
        # Should contain truncated version (60 chars + ellipsis)
        assert "A" * 60 in captured.out

    def test_ls_multimodal_content(self, tmp_path, capsys):
        """User content can be a list (multimodal) — should extract text parts."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "eeee-5555", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;..."}},
                {"type": "text", "text": "What is in this image?"},
            ]},
        ])

        args = mock.MagicMock()
        args.limit = 20

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_ls(args)

        captured = capsys.readouterr()
        assert "What is in this image?" in captured.out

    def test_ls_no_conversations(self, tmp_path, capsys):
        """When no conversations exist, ls should print nothing (no crash)."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        args = mock.MagicMock()
        args.limit = 20

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_ls(args)

        captured = capsys.readouterr()
        assert captured.out.strip() == ""

    def test_ls_no_user_messages(self, tmp_path, capsys):
        """Conversation with no user messages should still appear."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "ffff-6666", "2026-02-27T10:00:00+00:00", [
            {"role": "assistant", "content": "Hello!"},
        ])

        args = mock.MagicMock()
        args.limit = 20

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_ls(args)

        captured = capsys.readouterr()
        assert "ffff-66" in captured.out

    def test_ls_relative_age(self, tmp_path, capsys):
        """ls should show relative age of conversations."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "gggg-7777", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": "hello"},
        ])

        args = mock.MagicMock()
        args.limit = 20

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_ls(args)

        captured = capsys.readouterr()
        # Should have some age indicator (e.g., "5m", "2h", "3d", etc.)
        # The exact value depends on when the test runs, but the line should
        # have 3 visible fields: id, age, message
        lines = [l for l in captured.out.strip().splitlines() if l.strip()]
        assert len(lines) == 1
        parts = lines[0].split()
        # At minimum: short id and some age string
        assert len(parts) >= 2


# ---------------------------------------------------------------------------
# show command
# ---------------------------------------------------------------------------


class TestShowCommand:
    """Test the show subcommand that prints a full conversation transcript."""

    def _make_conv(self, conv_dir, conv_id, created, messages):
        """Write a conversation JSON file."""
        data = {"id": conv_id, "created": created, "messages": messages}
        (conv_dir / f"{conv_id}.json").write_text(json.dumps(data))

    def test_show_user_and_assistant(self, tmp_path, capsys):
        """show should print user and assistant messages with role prefixes."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "aaaa-1111", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ])

        args = mock.MagicMock()
        args.conversation_id = "aaaa-1111"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_show(args)

        captured = capsys.readouterr()
        lines = captured.out.strip().splitlines()
        assert lines[0] == "user: Hello"
        assert lines[1] == "assistant: Hi there!"

    def test_show_tool_calls(self, tmp_path, capsys):
        """show should display tool calls and tool results."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "bbbb-2222", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": "Search for cats"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "web_search", "arguments": '{"q": "cats"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "web_search", "content": "Cats are great pets."},
            {"role": "assistant", "content": "According to my search, cats are great pets."},
        ])

        args = mock.MagicMock()
        args.conversation_id = "bbbb-2222"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_show(args)

        captured = capsys.readouterr()
        lines = captured.out.strip().splitlines()
        assert lines[0] == "user: Search for cats"
        assert lines[1] == "assistant: [calling web_search]"
        assert lines[2] == "tool(web_search): Cats are great pets."
        assert lines[3] == "assistant: According to my search, cats are great pets."

    def test_show_tool_result_without_name(self, tmp_path, capsys):
        """Tool message without name field should resolve name from preceding tool_call."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "cccc-3333", "2026-02-27T10:00:00+00:00", [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_99",
                        "function": {"name": "read_file", "arguments": '{"path": "/tmp/x"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_99", "content": "file contents here"},
        ])

        args = mock.MagicMock()
        args.conversation_id = "cccc-3333"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_show(args)

        captured = capsys.readouterr()
        lines = captured.out.strip().splitlines()
        assert lines[0] == "assistant: [calling read_file]"
        assert lines[1] == "tool(read_file): file contents here"

    def test_show_multimodal_user_content(self, tmp_path, capsys):
        """User content can be a list (multimodal) — should extract text parts."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "dddd-4444", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;..."}},
                {"type": "text", "text": "What is in this image?"},
            ]},
            {"role": "assistant", "content": "I see a cat."},
        ])

        args = mock.MagicMock()
        args.conversation_id = "dddd-4444"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_show(args)

        captured = capsys.readouterr()
        lines = captured.out.strip().splitlines()
        assert lines[0] == "user: What is in this image?"
        assert lines[1] == "assistant: I see a cat."

    def test_show_not_found(self, tmp_path, capsys):
        """show should print an error and exit 1 if conversation not found."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        args = mock.MagicMock()
        args.conversation_id = "nonexistent-id"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                with pytest.raises(SystemExit) as exc_info:
                    _cmd_show(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()

    def test_show_multiple_tool_calls(self, tmp_path, capsys):
        """Assistant message with multiple tool_calls should show each one."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "eeee-5555", "2026-02-27T10:00:00+00:00", [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "web_search", "arguments": "{}"}},
                    {"id": "c2", "function": {"name": "read_file", "arguments": "{}"}},
                ],
            },
        ])

        args = mock.MagicMock()
        args.conversation_id = "eeee-5555"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_show(args)

        captured = capsys.readouterr()
        lines = captured.out.strip().splitlines()
        assert lines[0] == "assistant: [calling web_search]"
        assert lines[1] == "assistant: [calling read_file]"


# ---------------------------------------------------------------------------
# open command
# ---------------------------------------------------------------------------


class TestOpenCommand:
    """Test the open subcommand that exports a conversation to markdown."""

    def _make_conv(self, conv_dir, conv_id, created, messages):
        """Write a conversation JSON file."""
        data = {"id": conv_id, "created": created, "messages": messages}
        (conv_dir / f"{conv_id}.json").write_text(json.dumps(data))

    def test_open_creates_markdown(self, tmp_path):
        """open should write a markdown file at /tmp/aside-{id[:8]}.md."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "aaaa-1111", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ])

        args = mock.MagicMock()
        args.conversation_id = "aaaa-1111"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                with mock.patch("aside.cli.subprocess.Popen") as mock_popen:
                    _cmd_open(args)

        md_path = "/tmp/aside-aaaa-111.md"
        assert os.path.exists(md_path)

        content = Path(md_path).read_text()
        assert "# Conversation aaaa-111" in content
        assert "## User" in content
        assert "Hello" in content
        assert "## Assistant" in content
        assert "Hi there!" in content

        # Clean up
        os.unlink(md_path)

    def test_open_calls_xdg_open(self, tmp_path):
        """open should call xdg-open with the markdown file path."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "bbbb-2222", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": "Hello"},
        ])

        args = mock.MagicMock()
        args.conversation_id = "bbbb-2222"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                with mock.patch("aside.cli.subprocess.Popen") as mock_popen:
                    _cmd_open(args)

        mock_popen.assert_called_once_with(["xdg-open", "/tmp/aside-bbbb-222.md"])

        # Clean up
        md_path = "/tmp/aside-bbbb-222.md"
        if os.path.exists(md_path):
            os.unlink(md_path)

    def test_open_not_found(self, tmp_path, capsys):
        """open should print an error and exit 1 if conversation not found."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        args = mock.MagicMock()
        args.conversation_id = "nonexistent-id"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                with pytest.raises(SystemExit) as exc_info:
                    _cmd_open(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()

    def test_open_multimodal_content(self, tmp_path):
        """Multimodal user content should extract text parts in the markdown."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "cccc-3333", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;..."}},
                {"type": "text", "text": "What is in this image?"},
            ]},
            {"role": "assistant", "content": "I see a cat."},
        ])

        args = mock.MagicMock()
        args.conversation_id = "cccc-3333"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                with mock.patch("aside.cli.subprocess.Popen"):
                    _cmd_open(args)

        md_path = "/tmp/aside-cccc-333.md"
        content = Path(md_path).read_text()
        assert "What is in this image?" in content
        assert "I see a cat." in content

        # Clean up
        os.unlink(md_path)


# ---------------------------------------------------------------------------
# rm command
# ---------------------------------------------------------------------------


class TestRmCommand:
    """Test the rm subcommand that deletes a conversation."""

    def _make_conv(self, conv_dir, conv_id, created, messages):
        """Write a conversation JSON file."""
        data = {"id": conv_id, "created": created, "messages": messages}
        (conv_dir / f"{conv_id}.json").write_text(json.dumps(data))

    def test_rm_deletes_file(self, tmp_path):
        """rm should delete the conversation JSON file."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "aaaa-1111", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": "Hello"},
        ])

        conv_path = conv_dir / "aaaa-1111.json"
        assert conv_path.exists()

        args = mock.MagicMock()
        args.conversation_id = "aaaa-1111"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_rm(args)

        assert not conv_path.exists()

    def test_rm_prints_confirmation(self, tmp_path, capsys):
        """rm should print 'Deleted {id[:7]}' on success."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        self._make_conv(conv_dir, "bbbb-2222", "2026-02-27T10:00:00+00:00", [
            {"role": "user", "content": "Hello"},
        ])

        args = mock.MagicMock()
        args.conversation_id = "bbbb-2222"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                _cmd_rm(args)

        captured = capsys.readouterr()
        assert "Deleted bbbb-22" in captured.out

    def test_rm_not_found(self, tmp_path, capsys):
        """rm should print an error and exit 1 if conversation not found."""
        conv_dir = tmp_path / "conversations"
        conv_dir.mkdir()

        args = mock.MagicMock()
        args.conversation_id = "nonexistent-id"

        with mock.patch("aside.cli.load_config", return_value={}):
            with mock.patch("aside.cli.resolve_conversations_dir", return_value=conv_dir):
                with pytest.raises(SystemExit) as exc_info:
                    _cmd_rm(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()


# ---------------------------------------------------------------------------
# query command handler
# ---------------------------------------------------------------------------


class TestQueryCommand:
    """Test the query subcommand handler with --mic support."""

    def test_query_text_and_mic_exclusive(self, capsys):
        """Providing both text and --mic should print error and exit 1."""
        args = mock.MagicMock()
        args.text = "some text"
        args.mic = True
        args.new = False
        args.conversation_id = None

        with pytest.raises(SystemExit) as exc_info:
            _cmd_query(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err.lower()

    def test_query_requires_text_or_mic(self, capsys):
        """Providing neither text nor --mic should print error and exit 1."""
        args = mock.MagicMock()
        args.text = None
        args.mic = False
        args.new = False
        args.conversation_id = None

        with pytest.raises(SystemExit) as exc_info:
            _cmd_query(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "must provide" in captured.err.lower()

    def test_query_mic_sends_correct_json(self, monkeypatch):
        """query --mic should send mic:true with no text field."""
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))

        args = mock.MagicMock()
        args.text = None
        args.mic = True
        args.new = False
        args.conversation_id = None

        _cmd_query(args)

        assert len(sent) == 1
        assert sent[0]["action"] == "query"
        assert sent[0]["mic"] is True
        assert "text" not in sent[0]
        assert sent[0]["conversation_id"] is None

    def test_query_mic_with_conversation_id_sends_correct_json(self, monkeypatch):
        """query --mic -c CONV should send mic:true with conversation_id."""
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))

        args = mock.MagicMock()
        args.text = None
        args.mic = True
        args.new = False
        args.conversation_id = "conv-42"

        _cmd_query(args)

        assert len(sent) == 1
        assert sent[0]["action"] == "query"
        assert sent[0]["mic"] is True
        assert sent[0]["conversation_id"] == "conv-42"
        assert "text" not in sent[0]

    def test_query_mic_with_new_flag(self, monkeypatch):
        """query --mic --new should send mic:true with __new__ conversation_id."""
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))

        args = mock.MagicMock()
        args.text = None
        args.mic = True
        args.new = True
        args.conversation_id = None

        _cmd_query(args)

        assert len(sent) == 1
        assert sent[0]["action"] == "query"
        assert sent[0]["mic"] is True
        assert sent[0]["conversation_id"] == "__new__"

    def test_query_text_still_works(self, monkeypatch):
        """query TEXT should still send text as before."""
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))

        args = mock.MagicMock()
        args.text = "hello world"
        args.mic = False
        args.new = False
        args.conversation_id = None

        _cmd_query(args)

        assert len(sent) == 1
        assert sent[0]["action"] == "query"
        assert sent[0]["text"] == "hello world"
        assert "mic" not in sent[0]

    def test_query_mic_dispatch_via_main(self, monkeypatch):
        """aside query --mic via main() should dispatch correctly."""
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))

        with mock.patch("sys.argv", ["aside", "query", "--mic"]):
            main()

        assert len(sent) == 1
        assert sent[0]["action"] == "query"
        assert sent[0]["mic"] is True
        assert "text" not in sent[0]


# ---------------------------------------------------------------------------
# reply command
# ---------------------------------------------------------------------------


class TestReplyCommand:
    """Test the reply subcommand that continues a conversation."""

    def test_reply_text_sends_correct_json(self, monkeypatch, tmp_path):
        """reply ID TEXT should send a query with text and conversation_id."""
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))
        # Create conversation file so prefix resolution succeeds
        (tmp_path / "conv-42.json").write_text("{}")
        monkeypatch.setattr("aside.cli.resolve_conversations_dir", lambda cfg: tmp_path)

        args = mock.MagicMock()
        args.conversation_id = "conv-42"
        args.text = "follow up question"
        args.gui = False
        args.mic = False

        _cmd_reply(args)

        assert len(sent) == 1
        assert sent[0] == {
            "action": "query",
            "text": "follow up question",
            "conversation_id": "conv-42",
        }

    def test_reply_mic_sends_mic_flag(self, monkeypatch, tmp_path):
        """reply ID --mic should send mic:true with conversation_id."""
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))
        (tmp_path / "conv-42.json").write_text("{}")
        monkeypatch.setattr("aside.cli.resolve_conversations_dir", lambda cfg: tmp_path)

        args = mock.MagicMock()
        args.conversation_id = "conv-42"
        args.text = None
        args.gui = False
        args.mic = True

        _cmd_reply(args)

        assert len(sent) == 1
        assert sent[0] == {
            "action": "query",
            "conversation_id": "conv-42",
            "mic": True,
        }

    def test_reply_gui_launches_subprocess(self, monkeypatch, tmp_path):
        """reply ID --gui should launch aside-input subprocess."""
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))
        (tmp_path / "conv-42.json").write_text("{}")
        monkeypatch.setattr("aside.cli.resolve_conversations_dir", lambda cfg: tmp_path)

        args = mock.MagicMock()
        args.conversation_id = "conv-42"
        args.text = None
        args.gui = True
        args.mic = False

        with mock.patch("aside.cli.subprocess.Popen") as mock_popen:
            _cmd_reply(args)

        mock_popen.assert_called_once_with(["aside-input", "-c", "conv-42"])
        assert len(sent) == 0  # no socket message sent

    def test_reply_bare_prompts_for_input(self, monkeypatch, tmp_path):
        """Bare 'aside reply ID' should prompt for text, then send it."""
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))
        monkeypatch.setattr("builtins.input", lambda prompt: "typed reply")
        (tmp_path / "conv-42.json").write_text("{}")
        monkeypatch.setattr("aside.cli.resolve_conversations_dir", lambda cfg: tmp_path)

        args = mock.MagicMock()
        args.conversation_id = "conv-42"
        args.text = None
        args.gui = False
        args.mic = False

        _cmd_reply(args)

        assert len(sent) == 1
        assert sent[0] == {
            "action": "query",
            "text": "typed reply",
            "conversation_id": "conv-42",
        }

    def test_reply_text_and_mic_errors(self, capsys):
        """Providing both text and --mic should print error and exit 1."""
        args = mock.MagicMock()
        args.conversation_id = "conv-42"
        args.text = "some text"
        args.gui = False
        args.mic = True

        with pytest.raises(SystemExit) as exc_info:
            _cmd_reply(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err.lower() or "--mic" in captured.err

    def test_reply_gui_and_mic_errors(self, capsys):
        """Providing both --gui and --mic should print error and exit 1."""
        args = mock.MagicMock()
        args.conversation_id = "conv-42"
        args.text = None
        args.gui = True
        args.mic = True

        with pytest.raises(SystemExit) as exc_info:
            _cmd_reply(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err.lower() or "--mic" in captured.err

    def test_reply_dispatch_via_main(self, monkeypatch, tmp_path):
        """aside reply conv-42 'text' via main() should dispatch correctly."""
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))
        (tmp_path / "conv-42.json").write_text("{}")
        monkeypatch.setattr("aside.cli.resolve_conversations_dir", lambda cfg: tmp_path)

        with mock.patch("sys.argv", ["aside", "reply", "conv-42", "hello again"]):
            main()

        assert len(sent) == 1
        assert sent[0]["action"] == "query"
        assert sent[0]["text"] == "hello again"
        assert sent[0]["conversation_id"] == "conv-42"


# ---------------------------------------------------------------------------
# set-key command
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# get-key command
# ---------------------------------------------------------------------------


class TestGetKeyCommand:
    def test_get_key_found(self, capsys):
        args = mock.Mock(provider="anthropic")
        with mock.patch("aside.keyring.get_key", return_value="sk-ant-1234567890abcdef"):
            _cmd_get_key(args)
        out = capsys.readouterr().out
        assert "sk-a..." in out
        assert "cdef" in out

    def test_get_key_not_found(self, capsys):
        args = mock.Mock(provider="openai")
        with mock.patch("aside.keyring.get_key", return_value=None):
            with mock.patch("aside.keyring._PROVIDER_TO_ENV", {"openai": "OPENAI_API_KEY"}):
                with mock.patch.dict(os.environ, {}, clear=True):
                    _cmd_get_key(args)
        out = capsys.readouterr().out
        assert "not found" in out.lower()


# ---------------------------------------------------------------------------
# _send_recv helper
# ---------------------------------------------------------------------------


class TestSendRecv:
    def test_send_recv_returns_response(self, tmp_path):
        """_send_recv sends JSON and returns the parsed JSON response."""
        import asyncio
        import threading

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

        loop = asyncio.new_event_loop()

        def run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=run_loop, daemon=True)
        t.start()

        srv = asyncio.run_coroutine_threadsafe(echo_server(), loop).result(timeout=5)
        try:
            with mock.patch("aside.cli.resolve_socket_path", return_value=sock_path):
                result = _send_recv({"action": "get_model"})
            assert result == {"action": "get_model"}
        finally:
            loop.call_soon_threadsafe(srv.close)
            loop.call_soon_threadsafe(loop.stop)
            t.join(timeout=5)

    def test_send_recv_daemon_not_running(self, tmp_path):
        with mock.patch("aside.cli.resolve_socket_path", return_value=tmp_path / "nope.sock"):
            with pytest.raises(SystemExit):
                _send_recv({"action": "get_model"})


# ---------------------------------------------------------------------------
# Daemon model actions
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# models / model commands
# ---------------------------------------------------------------------------


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
                _cmd_models(mock.Mock())

        out = capsys.readouterr().out
        assert "anthropic" in out
        assert "* anthropic/claude-haiku-4-5" in out
        assert "  anthropic/claude-sonnet-4-6" in out
        assert "gemini" in out

    def test_model_set_sends_socket_message(self):
        with mock.patch("aside.cli._send") as mock_send:
            args = mock.Mock()
            args.model_action = "set"
            args.name = "gemini/gemini-2.5-pro"
            _cmd_model(args)
            mock_send.assert_called_once_with({"action": "set_model", "model": "gemini/gemini-2.5-pro"})
