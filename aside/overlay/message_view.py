"""Single message display widget for the aside overlay."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from aside.overlay.markdown import render_to_buffer  # noqa: E402


class MessageView(Gtk.Box):
    """Displays a single user or assistant message with optional markdown."""

    def __init__(self, role: str, text: str = "", markdown: bool = True) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._role = role
        self._raw_text = text
        self._markdown = markdown

        # CSS classes
        self.add_css_class("message-view")
        if role == "user":
            self.add_css_class("message-user")
        else:
            self.add_css_class("message-llm")

        # Read-only TextView
        self._textview = Gtk.TextView()
        self._textview.set_editable(False)
        self._textview.set_cursor_visible(False)
        self._textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._textview.set_top_margin(4)
        self._textview.set_bottom_margin(4)
        self._textview.set_left_margin(16)
        self._textview.set_right_margin(16)
        self.append(self._textview)

        # Initial render
        if text:
            self._render()

    @property
    def role(self) -> str:
        return self._role

    def set_text(self, text: str) -> None:
        """Update the raw text and re-render."""
        self._raw_text = text
        self._render()

    def get_raw_text(self) -> str:
        """Return the raw markdown source text."""
        return self._raw_text

    def get_buffer(self) -> Gtk.TextBuffer:
        """Return the underlying TextBuffer."""
        return self._textview.get_buffer()

    def _render(self) -> None:
        """Render _raw_text into the TextBuffer."""
        render_to_buffer(
            self._textview.get_buffer(),
            self._raw_text,
            enabled=self._markdown,
        )
