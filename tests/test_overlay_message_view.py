"""Tests for aside.overlay.message_view — single message display widget."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.message_view import MessageView


class TestMessageView:
    def test_create_llm_message(self):
        mv = MessageView(role="assistant", text="Hello", markdown=True)
        assert mv.role == "assistant"

    def test_create_user_message(self):
        mv = MessageView(role="user", text="Hi there", markdown=True)
        assert mv.role == "user"

    def test_set_text(self):
        mv = MessageView(role="assistant", text="Hello", markdown=True)
        mv.set_text("Hello world")
        buf = mv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert "world" in text

    def test_get_raw_text(self):
        mv = MessageView(role="assistant", text="Test content", markdown=True)
        assert mv.get_raw_text() == "Test content"

    def test_plain_text_mode(self):
        mv = MessageView(role="assistant", text="**bold**", markdown=False)
        buf = mv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert text == "**bold**"
