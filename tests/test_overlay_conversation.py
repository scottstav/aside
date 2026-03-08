"""Tests for aside.overlay.conversation — scrollable message history."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.conversation import ConversationHistory


class TestConversationHistory:
    def test_create_empty(self):
        ch = ConversationHistory(markdown=True)
        assert ch.message_count() == 0

    def test_add_message(self):
        ch = ConversationHistory(markdown=True)
        ch.add_message("assistant", "Hello")
        assert ch.message_count() == 1

    def test_add_multiple_messages(self):
        ch = ConversationHistory(markdown=True)
        ch.add_message("user", "Hi")
        ch.add_message("assistant", "Hello!")
        assert ch.message_count() == 2

    def test_clear(self):
        ch = ConversationHistory(markdown=True)
        ch.add_message("assistant", "Hello")
        ch.clear()
        assert ch.message_count() == 0

    def test_load_conversation(self):
        conv = {
            "id": "test-123",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ]
        }
        ch = ConversationHistory(markdown=True)
        ch.load_conversation(conv)
        assert ch.message_count() == 2

    def test_update_last_message(self):
        ch = ConversationHistory(markdown=True)
        ch.add_message("assistant", "Hello")
        ch.update_last_message("Hello world")
        last = ch.get_last_message()
        assert last.get_raw_text() == "Hello world"
