"""GTK4 + libadwaita input popup for aside.

A floating popup window for typing queries to the aside daemon.
Launched by a keybind, it shows recent conversations and a text entry.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import socket
from datetime import datetime, timezone

# gtk4-layer-shell must be loaded before libwayland-client.  If the library
# is available, preload it via ctypes so the GI typelib works correctly even
# when Python (or the linker) would otherwise load libwayland first.
# See https://github.com/wmww/gtk4-layer-shell/blob/main/linking.md
_LAYER_SHELL_LIB = os.environ.get("GTK4_LAYER_SHELL_LIB", "libgtk4-layer-shell.so")
try:
    ctypes.CDLL(_LAYER_SHELL_LIB, mode=ctypes.RTLD_GLOBAL)
except OSError:
    pass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Adw, Gdk, GLib, Gtk, Gtk4LayerShell  # noqa: E402

from aside.config import load_config, resolve_conversations_dir, resolve_socket_path  # noqa: E402
from aside.state import ConversationStore  # noqa: E402

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = """
window {
    background-color: transparent;
}
window.background {
    background-color: transparent;
}
.input-container {
    background-color: alpha(@window_bg_color, 0.92);
    border-radius: 16px;
    border: 1px solid alpha(@accent_color, 0.25);
    padding: 0;
}
.input-title {
    font-weight: bold;
    padding: 14px 0 8px 0;
    color: @window_fg_color;
}
.input-listbox {
    background: transparent;
    border-radius: 0;
}
.input-listbox row {
    border-radius: 8px;
    margin: 2px 8px;
}
.input-listbox row:selected {
    background-color: alpha(@accent_color, 0.15);
}
.input-textview {
    background-color: alpha(@window_fg_color, 0.04);
    border-radius: 10px;
    border: 1px solid alpha(@accent_color, 0.4);
    padding: 8px;
    caret-color: @accent_color;
}
.input-textview:focus {
    border-color: @accent_color;
    box-shadow: 0 0 0 1px alpha(@accent_color, 0.3);
}
.input-hint {
    font-size: 0.8em;
    color: alpha(@window_fg_color, 0.35);
}
"""

# ---------------------------------------------------------------------------
# Socket communication
# ---------------------------------------------------------------------------


def _send_to_daemon(msg: dict) -> None:
    """Send a JSON message to the aside daemon over its Unix socket."""
    sock_path = resolve_socket_path()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(sock_path))
        s.sendall((json.dumps(msg) + "\n").encode())
        s.close()
    except OSError:
        log.exception("Failed to send message to daemon at %s", sock_path)


# ---------------------------------------------------------------------------
# Conversation row helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------


class AsideInputWindow(Gtk.Window):
    """The popup input window."""

    def __init__(self, app: Adw.Application, config: dict) -> None:
        super().__init__(application=app)
        self._config = config
        self._selected_conv_id: str | None = None

        self.set_title("aside")
        self.set_default_size(500, 400)

        # Layer shell setup
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_keyboard_mode(
            self, Gtk4LayerShell.KeyboardMode.ON_DEMAND
        )

        # CSS
        css_text = CSS
        font = config.get("input", {}).get("font", "")
        if font:
            from gi.repository import Pango
            desc = Pango.FontDescription.from_string(font)
            family = desc.get_family()
            parts = [f'font-family: "{family}"']
            size = desc.get_size()
            if size:
                pts = size / Pango.SCALE
                parts.append(f"font-size: {pts}pt")
            css_text += "\n* { " + "; ".join(parts) + "; }"
        provider = Gtk.CssProvider()
        provider.load_from_string(css_text)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Build UI
        self._build_ui()

        # Keyboard shortcuts
        self._setup_shortcuts()

    def _build_ui(self) -> None:
        """Construct the widget tree."""
        # Outer container with rounded corners and semi-transparent bg
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        container.add_css_class("input-container")
        self.set_child(container)

        # -- Title --
        title = Gtk.Label(label="aside")
        title.add_css_class("input-title")
        container.append(title)

        # -- Conversation list --
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        container.append(scrolled)

        self._listbox = Gtk.ListBox()
        self._listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._listbox.add_css_class("input-listbox")
        self._listbox.connect("row-selected", self._on_row_selected)
        scrolled.set_child(self._listbox)

        self._populate_conversations()

        # -- Text input area --
        input_scroll = Gtk.ScrolledWindow()
        input_scroll.set_min_content_height(80)
        input_scroll.set_max_content_height(160)
        input_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        input_scroll.set_margin_start(12)
        input_scroll.set_margin_end(12)
        input_scroll.set_margin_top(8)
        input_scroll.set_margin_bottom(4)
        input_scroll.add_css_class("input-textview")
        container.append(input_scroll)

        self._textview = Gtk.TextView()
        self._textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._textview.set_left_margin(4)
        self._textview.set_right_margin(4)
        self._textview.set_top_margin(4)
        self._textview.set_bottom_margin(4)
        self._textview.grab_focus()
        input_scroll.set_child(self._textview)

        # Key controller on textview for Enter handling
        tv_key = Gtk.EventControllerKey()
        tv_key.connect("key-pressed", self._on_input_key)
        self._textview.add_controller(tv_key)

        # -- Hint label --
        hint = Gtk.Label(label="Enter to send  |  Shift+Enter for newline  |  Escape to close")
        hint.add_css_class("input-hint")
        hint.set_margin_top(4)
        hint.set_margin_bottom(10)
        container.append(hint)

    def _populate_conversations(self) -> None:
        """Load recent conversations into the list box."""
        # New conversation row (always first)
        new_row = _make_new_conversation_row()
        self._listbox.append(new_row)
        self._listbox.select_row(new_row)
        self._selected_conv_id = _NEW_CONVERSATION_ID

        # Recent conversations
        try:
            conv_dir = resolve_conversations_dir(self._config)
            if conv_dir.is_dir():
                store = ConversationStore(conv_dir)
                for conv_id, created, preview in store.list_recent(limit=15):
                    row = _make_conversation_row(conv_id, created, preview)
                    self._listbox.append(row)
        except Exception:
            log.exception("Failed to load conversations")

    def _on_row_selected(
        self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        """Track which conversation is selected."""
        if row is not None:
            self._selected_conv_id = row._conversation_id  # type: ignore[attr-defined]
        else:
            self._selected_conv_id = _NEW_CONVERSATION_ID

    def _setup_shortcuts(self) -> None:
        """Register keyboard shortcuts."""
        # Escape -> close
        esc_controller = Gtk.EventControllerKey()
        esc_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(esc_controller)

    def _on_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        """Handle key press events."""
        # Escape -> close
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True

        # Ctrl+N / Ctrl+P -> navigate conversation list
        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval in (Gdk.KEY_n, Gdk.KEY_p):
                row = self._listbox.get_selected_row()
                if row is not None:
                    idx = row.get_index()
                    if keyval == Gdk.KEY_n:
                        next_row = self._listbox.get_row_at_index(idx + 1)
                    else:
                        next_row = self._listbox.get_row_at_index(max(0, idx - 1))
                    if next_row is not None:
                        self._listbox.select_row(next_row)
                return True

        # Tab -> select conversation and focus input
        if keyval == Gdk.KEY_Tab:
            self._textview.grab_focus()
            return True

        return False

    def _on_input_key(self, ctl: Gtk.EventControllerKey,
                      keyval: int, keycode: int, state: Gdk.ModifierType) -> bool:
        """Handle key presses inside the text input."""
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if state & Gdk.ModifierType.SHIFT_MASK:
                return False  # let GTK insert newline
            self._submit()
            return True
        return False

    def _submit(self) -> None:
        """Read the text entry, send to daemon, close the window."""
        buf = self._textview.get_buffer()
        start = buf.get_start_iter()
        end = buf.get_end_iter()
        text = buf.get_text(start, end, False).strip()

        if not text:
            return

        # Determine conversation_id to send
        conv_id: str | None = None
        if self._selected_conv_id == _NEW_CONVERSATION_ID:
            conv_id = _NEW_CONVERSATION_ID
        elif self._selected_conv_id:
            conv_id = self._selected_conv_id

        msg = {
            "action": "query",
            "text": text,
            "conversation_id": conv_id,
        }

        # Send in a thread so GTK doesn't block
        import threading

        threading.Thread(target=_send_to_daemon, args=(msg,), daemon=True).start()

        self.close()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class AsideInput(Adw.Application):
    """GTK4 application wrapper."""

    def __init__(self) -> None:
        super().__init__(application_id="dev.aside.input")
        self._config = load_config()

    def do_activate(self) -> None:
        """Create and present the input window."""
        win = AsideInputWindow(self, self._config)
        win.present()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Launch the aside input popup."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    app = AsideInput()
    app.run()


if __name__ == "__main__":
    main()
