"""Tests for aside.overlay.app — socket command parsing."""

from aside.overlay.app import parse_command


class TestParseCommand:
    def test_open(self):
        cmd = parse_command('{"cmd":"open","mode":"user"}')
        assert cmd == {"cmd": "open", "mode": "user"}

    def test_text(self):
        cmd = parse_command('{"cmd":"text","data":"hello"}')
        assert cmd == {"cmd": "text", "data": "hello"}

    def test_input(self):
        cmd = parse_command('{"cmd":"input"}')
        assert cmd == {"cmd": "input"}

    def test_reply(self):
        cmd = parse_command('{"cmd":"reply","conversation_id":"abc-123"}')
        assert cmd == {"cmd": "reply", "conversation_id": "abc-123"}

    def test_invalid_json_returns_none(self):
        assert parse_command("not json") is None

    def test_empty_returns_none(self):
        assert parse_command("") is None
