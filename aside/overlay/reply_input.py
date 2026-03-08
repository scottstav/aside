"""ReplyInput — text entry widget for reply/conversation modes."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk


class ReplyInput(Gtk.Box):
    """Vertical box containing a scrollable text entry and hint label."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("reply-input-container")

        # Scrolled window for the text view
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_min_content_height(32)
        self._scroll.set_max_content_height(160)
        self._scroll.set_propagate_natural_height(True)
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Editable text view
        self._textview = Gtk.TextView()
        self._textview.set_editable(True)
        self._textview.set_wrap_mode(Gtk.WrapMode.WORD)
        self._textview.add_css_class("reply-input")
        self._scroll.set_child(self._textview)

        # Hint label
        self._hint = Gtk.Label(label="Enter to send \u2022 Shift+Enter for newline \u2022 Esc to close")
        self._hint.add_css_class("input-hint")

        self.append(self._scroll)
        self.append(self._hint)

    def get_text(self) -> str:
        """Return stripped text from the buffer."""
        buf = self._textview.get_buffer()
        start = buf.get_start_iter()
        end = buf.get_end_iter()
        return buf.get_text(start, end, False).strip()

    def clear(self) -> None:
        """Clear the text buffer."""
        buf = self._textview.get_buffer()
        buf.set_text("")

    def connect_submit(self, callback: Callable[[str], None]) -> None:
        """Register a callback for Enter key (not Shift+Enter)."""
        controller = Gtk.EventControllerKey()

        def on_key_pressed(
            _ctrl: Gtk.EventControllerKey,
            keyval: int,
            _keycode: int,
            state: Gdk.ModifierType,
        ) -> bool:
            if keyval == Gdk.KEY_Return and not (state & Gdk.ModifierType.SHIFT_MASK):
                text = self.get_text()
                if text:
                    callback(text)
                return True
            return False

        controller.connect("key-pressed", on_key_pressed)
        self._textview.add_controller(controller)

    def focus_input(self) -> None:
        """Grab focus on the text view."""
        self._textview.grab_focus()
