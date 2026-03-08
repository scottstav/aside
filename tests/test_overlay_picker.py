"""Tests for aside.overlay.picker — conversation list selector."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.picker import ConversationPicker


class TestConversationPicker:
    def test_create(self):
        picker = ConversationPicker()
        assert isinstance(picker, Gtk.Box)

    def test_populate(self):
        entries = [
            ("id-1", "2026-03-08T12:00:00+00:00", "First conversation"),
            ("id-2", "2026-03-07T10:00:00+00:00", "Second conversation"),
        ]
        picker = ConversationPicker()
        picker.populate(entries)
        # Should have 3 rows: "New conversation" + 2 entries
        assert picker.row_count() == 3

    def test_new_conversation_is_first(self):
        picker = ConversationPicker()
        picker.populate([])
        assert picker.get_selected_id() == "__new__"

    def test_has_text_input(self):
        picker = ConversationPicker()
        assert picker.get_text() == ""
