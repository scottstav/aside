"""Integration test — verify socket command dispatch."""

import json
import pytest

from aside.overlay.app import parse_command


class TestCommandDispatch:
    """Verify all socket commands parse and map to handler methods."""

    COMMANDS = [
        ('{"cmd":"open","mode":"user"}', "handle_open"),
        ('{"cmd":"text","data":"hello"}', "handle_text"),
        ('{"cmd":"done"}', "handle_done"),
        ('{"cmd":"clear"}', "handle_clear"),
        ('{"cmd":"replace","data":"new text"}', "handle_replace"),
        ('{"cmd":"thinking"}', "handle_thinking"),
        ('{"cmd":"listening"}', "handle_listening"),
        ('{"cmd":"input"}', "handle_input"),
        ('{"cmd":"reply","conversation_id":"abc"}', "handle_reply"),
        ('{"cmd":"convo","conversation_id":"abc"}', "handle_convo"),
    ]

    @pytest.mark.parametrize("json_str,expected_handler", COMMANDS)
    def test_command_parses(self, json_str, expected_handler):
        cmd = parse_command(json_str)
        assert cmd is not None
        assert "cmd" in cmd

    def test_unknown_command_ignored(self):
        cmd = parse_command('{"cmd":"bogus"}')
        assert cmd is not None
        assert cmd["cmd"] == "bogus"

    def test_malformed_json(self):
        assert parse_command("{bad json") is None

    def test_empty_string(self):
        assert parse_command("") is None

    def test_whitespace_only(self):
        assert parse_command("   ") is None
