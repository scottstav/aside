"""ConversationPicker — conversation list selector widget."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk

_NEW_CONVERSATION_ID = "__new__"


def _format_date(iso_str: str) -> str:
    """Format an ISO date string into a short human-readable form."""
    try:
        dt = datetime.fromisoformat(iso_str)
        now = datetime.now(timezone.utc)
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        return dt.strftime("%b %d")
    except (ValueError, TypeError):
        return ""


def _make_conversation_row(
    conv_id: str, date_str: str, preview: str
) -> Gtk.ListBoxRow:
    """Build a ListBoxRow for a single conversation."""
    row = Gtk.ListBoxRow()
    row._conversation_id = conv_id  # type: ignore[attr-defined]

    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    hbox.set_margin_start(12)
    hbox.set_margin_end(12)
    hbox.set_margin_top(6)
    hbox.set_margin_bottom(6)

    date_label = Gtk.Label(label=_format_date(date_str))
    date_label.add_css_class("dim-label")
    date_label.set_xalign(0)
    date_label.set_size_request(50, -1)
    hbox.append(date_label)

    preview_text = preview[:80].replace("\n", " ").strip() or "(empty)"
    preview_label = Gtk.Label(label=preview_text)
    preview_label.set_xalign(0)
    preview_label.set_hexpand(True)
    preview_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
    hbox.append(preview_label)

    row.set_child(hbox)
    return row


def _make_new_conversation_row() -> Gtk.ListBoxRow:
    """Build the 'New conversation' row."""
    row = Gtk.ListBoxRow()
    row._conversation_id = _NEW_CONVERSATION_ID  # type: ignore[attr-defined]

    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    hbox.set_margin_start(12)
    hbox.set_margin_end(12)
    hbox.set_margin_top(6)
    hbox.set_margin_bottom(6)

    icon = Gtk.Label(label="+")
    icon.add_css_class("accent")
    icon.set_size_request(50, -1)
    icon.set_xalign(0)
    hbox.append(icon)

    label = Gtk.Label(label="New conversation")
    label.set_xalign(0)
    label.set_hexpand(True)
    hbox.append(label)

    row.set_child(hbox)
    return row


class ConversationPicker(Gtk.Box):
    """Vertical box with conversation list and text input for queries."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("picker")

        # Title
        title = Gtk.Label(label="aside")
        title.add_css_class("picker-title")
        self.append(title)

        # Conversation list
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_vexpand(True)
        list_scroll.set_min_content_height(200)
        list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(list_scroll)

        self._listbox = Gtk.ListBox()
        self._listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._listbox.add_css_class("picker-listbox")
        list_scroll.set_child(self._listbox)

        # Text input
        input_scroll = Gtk.ScrolledWindow()
        input_scroll.set_min_content_height(80)
        input_scroll.set_max_content_height(160)
        input_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        input_scroll.set_margin_start(12)
        input_scroll.set_margin_end(12)
        input_scroll.set_margin_top(8)
        input_scroll.set_margin_bottom(4)
        input_scroll.add_css_class("picker-input")
        self.append(input_scroll)

        self._textview = Gtk.TextView()
        self._textview.set_editable(True)
        self._textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._textview.set_left_margin(4)
        self._textview.set_right_margin(4)
        self._textview.set_top_margin(4)
        self._textview.set_bottom_margin(4)
        input_scroll.set_child(self._textview)

        # Hint label
        hint = Gtk.Label(
            label="Enter to send | Shift+Enter for newline | Escape to close"
        )
        hint.add_css_class("input-hint")
        hint.set_margin_top(4)
        hint.set_margin_bottom(10)
        self.append(hint)

        # Keyboard navigation
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)

    def _on_key(self, ctl, keyval, keycode, state) -> bool:
        ctrl = state & Gdk.ModifierType.CONTROL_MASK

        if keyval == Gdk.KEY_Tab:
            self._textview.grab_focus()
            return True

        if ctrl and keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self._select_adjacent(1)
            return True

        if ctrl and keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self._select_adjacent(-1)
            return True

        if keyval in (Gdk.KEY_Down,):
            self._select_adjacent(1)
            return True

        if keyval in (Gdk.KEY_Up,):
            self._select_adjacent(-1)
            return True

        return False

    def _select_adjacent(self, delta: int) -> None:
        """Select the row delta positions from current selection."""
        current = self._listbox.get_selected_row()
        if current is None:
            idx = 0
        else:
            idx = current.get_index() + delta
        target = self._listbox.get_row_at_index(idx)
        if target is not None:
            self._listbox.select_row(target)

    def populate(self, entries: list[tuple[str, str, str]]) -> None:
        """Clear listbox and populate with new-conversation row + entries."""
        # Remove all existing rows
        while True:
            row = self._listbox.get_row_at_index(0)
            if row is None:
                break
            self._listbox.remove(row)

        # Always add "New conversation" first
        new_row = _make_new_conversation_row()
        self._listbox.append(new_row)
        self._listbox.select_row(new_row)

        # Add conversation entries
        for conv_id, date_str, preview in entries:
            row = _make_conversation_row(conv_id, date_str, preview)
            self._listbox.append(row)

    def get_selected_id(self) -> str:
        """Return the conversation ID of the selected row."""
        row = self._listbox.get_selected_row()
        if row is not None:
            return row._conversation_id  # type: ignore[attr-defined]
        return _NEW_CONVERSATION_ID

    def get_text(self) -> str:
        """Return stripped text from the input buffer."""
        buf = self._textview.get_buffer()
        start = buf.get_start_iter()
        end = buf.get_end_iter()
        return buf.get_text(start, end, False).strip()

    def row_count(self) -> int:
        """Return the number of rows in the listbox."""
        count = 0
        while self._listbox.get_row_at_index(count) is not None:
            count += 1
        return count

    def connect_submit(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for Enter key submission.

        The callback receives (text, conversation_id).
        """
        controller = Gtk.EventControllerKey()

        def on_key_pressed(
            _ctrl: Gtk.EventControllerKey,
            keyval: int,
            _keycode: int,
            state: Gdk.ModifierType,
        ) -> bool:
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                if state & Gdk.ModifierType.SHIFT_MASK:
                    return False  # let GTK insert newline
                text = self.get_text()
                if text:
                    callback(text, self.get_selected_id())
                return True
            return False

        controller.connect("key-pressed", on_key_pressed)
        self._textview.add_controller(controller)

    def focus_input(self) -> None:
        """Grab focus on the text view."""
        self._textview.grab_focus()
