"""Tests for aside.overlay.markdown — markdown to TextBuffer+TextTags."""

import gi
gi.require_version("Gtk", "4.0")

import pytest

try:
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.markdown import render_to_buffer


class TestRenderToBuffer:
    def _make_buffer(self):
        buf = Gtk.TextBuffer()
        return buf

    def test_plain_text(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "Hello world")
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert text == "Hello world"

    def test_bold(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "Hello **bold** world")
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert "bold" in text
        # Verify bold tag exists
        tag_table = buf.get_tag_table()
        assert tag_table.lookup("bold") is not None

    def test_code_span(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "Use `foo()` here")
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert "foo()" in text
        tag_table = buf.get_tag_table()
        assert tag_table.lookup("code") is not None

    def test_code_block(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "```python\nprint('hi')\n```")
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert "print('hi')" in text
        tag_table = buf.get_tag_table()
        assert tag_table.lookup("code-block") is not None

    def test_heading(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "# Title\nBody text")
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert "Title" in text

    def test_disabled_returns_plain(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "**bold** `code`", enabled=False)
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert text == "**bold** `code`"
