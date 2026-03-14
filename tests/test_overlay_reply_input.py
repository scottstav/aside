"""Tests for aside.overlay.reply_input — text entry widget."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.reply_input import ReplyInput


class TestReplyInput:
    def test_create(self):
        ri = ReplyInput()
        assert isinstance(ri, Gtk.Box)

    def test_get_text_empty(self):
        ri = ReplyInput()
        assert ri.get_text() == ""

    def test_clear(self):
        ri = ReplyInput()
        ri.clear()
        assert ri.get_text() == ""

    def test_has_css_class(self):
        ri = ReplyInput()
        assert ri.has_css_class("reply-input-container")
