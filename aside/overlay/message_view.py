"""Single message display widget for the aside overlay."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from aside.overlay.markdown import render_to_buffer  # noqa: E402


class MessageView(Gtk.Box):
    """Displays a single user or assistant message with optional markdown."""

    def __init__(self, role: str, text: str = "", markdown: bool = True) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._role = role
        self._raw_text = text
        self._markdown = markdown
        self._render_retry_id: int | None = None

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

    @property
    def role(self) -> str:
        return self._role

    def set_text(self, text: str) -> None:
        """Update the raw text and re-render when the widget is ready."""
        self._raw_text = text
        if self._textview.get_allocated_width() > 0:
            self._render()
        elif text and self._render_retry_id is None:
            # Widget has no allocation yet — retry next frame.
            self._render_retry_id = GLib.timeout_add(16, self._retry_render)

    def _retry_render(self) -> bool:
        """Retry rendering once the widget has a valid allocation."""
        self._render_retry_id = None
        if self._raw_text:
            if self._textview.get_allocated_width() > 0:
                self._render()
                # Force the entire parent chain to re-measure — the initial
                # 0-height allocation is cached up the tree.
                widget = self._textview
                while widget is not None:
                    widget.queue_resize()
                    widget = widget.get_parent()
            else:
                self._render_retry_id = GLib.timeout_add(16, self._retry_render)
        return False

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
