"""GTK4 layer-shell action bar for aside overlay.

Appears below the overlay after a query completes.
Shows action buttons (mic, open, reply) and transitions
to a text input box when reply is clicked.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import socket
import sys
import threading

_LAYER_SHELL_LIB = os.environ.get("GTK4_LAYER_SHELL_LIB", "libgtk4-layer-shell.so")
try:
    ctypes.CDLL(_LAYER_SHELL_LIB, mode=ctypes.RTLD_GLOBAL)
except OSError:
    pass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Adw, Gdk, GLib, Gtk, Gtk4LayerShell

from aside.config import load_config, resolve_socket_path

log = logging.getLogger(__name__)


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


CSS = """
window {
    background-color: transparent;
}
window.background {
    background-color: transparent;
}
.action-bar {
    background-color: alpha(@window_bg_color, 0.90);
    border-radius: 14px;
    border: 1px solid alpha(@accent_color, 0.25);
    padding: 2px;
    margin: 0;
}
button.action-btn {
    border-radius: 10px;
    padding: 2px 8px;
    min-height: 0;
    min-width: 0;
    margin: 0;
    background: transparent;
    border: none;
    color: alpha(@window_fg_color, 0.5);
    -gtk-icon-size: 14px;
}
button.action-btn:hover {
    background: alpha(@accent_color, 0.15);
    color: @accent_color;
}
button.action-btn:active {
    background: alpha(@accent_color, 0.25);
}
.input-bar {
    background-color: alpha(@window_bg_color, 0.95);
    border-radius: 12px;
    border: 1px solid alpha(@accent_color, 0.3);
    padding: 4px;
}
.reply-input {
    background-color: alpha(@window_fg_color, 0.04);
    border-radius: 6px;
    border: 1px solid alpha(@accent_color, 0.5);
    padding: 8px;
    caret-color: @accent_color;
}
.reply-input:focus {
    border-color: @accent_color;
    box-shadow: 0 0 0 1px alpha(@accent_color, 0.3);
}
.reply-hint {
    font-size: 0.8em;
    color: alpha(@window_fg_color, 0.4);
    margin-top: 2px;
}
"""


class ActionsWindow(Gtk.Window):
    """Layer-shell action bar that appears below the overlay."""

    def __init__(self, app: Adw.Application, conv_id: str,
                 width: int, margin_top: int,
                 reposition_fd: int | None = None,
                 hold_fd: int | None = None,
                 position: str = "top-center",
                 margin_left: int = 0,
                 margin_right: int = 0) -> None:
        super().__init__(application=app)
        self._conv_id = conv_id
        self._input_width = width
        self._hold_fd = hold_fd
        self._pointer_in = False
        self._in_input_mode = False
        self._holding = False

        self.set_title("aside-actions")
        self.set_decorated(False)
        self.set_resizable(False)

        # Layer shell setup — match overlay anchoring
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, margin_top)

        # Horizontal anchoring to follow overlay position
        if "left" in position:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.LEFT, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.LEFT, margin_left)
        elif "right" in position:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.RIGHT, margin_right)

        Gtk4LayerShell.set_keyboard_mode(
            self, Gtk4LayerShell.KeyboardMode.NONE
        )
        Gtk4LayerShell.set_namespace(self, "aside-actions")

        # CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Build UI
        self._stack = Gtk.Stack()
        self._stack.set_vhomogeneous(False)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)

        self._build_button_mode()
        self._build_input_mode()
        self.set_child(self._stack)

        # Keyboard shortcuts
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)

        # Pointer enter/leave to signal hold to overlay
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_pointer_enter)
        motion.connect("leave", self._on_pointer_leave)
        self.add_controller(motion)

        # Watch for reposition messages from overlay (pipe fd)
        if reposition_fd is not None:
            threading.Thread(
                target=self._watch_reposition, args=(reposition_fd,),
                daemon=True,
            ).start()

    def _watch_reposition(self, fd: int) -> None:
        """Read margin-top updates from the overlay over a pipe."""
        buf = b""
        while True:
            try:
                data = os.read(fd, 256)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    margin = int(line)
                    GLib.idle_add(self._update_margin, margin)
                except ValueError:
                    pass
        try:
            os.close(fd)
        except OSError:
            pass

    def _update_margin(self, margin: int) -> bool:
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, margin)
        return False

    # -- Hold signalling to overlay --

    def _send_hold(self, hold: bool) -> None:
        if self._hold_fd is not None:
            try:
                os.write(self._hold_fd, b"H" if hold else b"R")
            except OSError:
                pass

    def _update_hold(self) -> None:
        should_hold = self._pointer_in or self._in_input_mode
        if should_hold != self._holding:
            self._holding = should_hold
            self._send_hold(should_hold)

    def _on_pointer_enter(self, ctl: Gtk.EventControllerMotion,
                          x: float, y: float) -> None:
        self._pointer_in = True
        self._update_hold()

    def _on_pointer_leave(self, ctl: Gtk.EventControllerMotion) -> None:
        self._pointer_in = False
        self._update_hold()

    def _build_button_mode(self) -> None:
        """Create the action buttons view."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        box.add_css_class("action-bar")
        box.set_halign(Gtk.Align.CENTER)

        for icon_name, tooltip, callback in [
            ("audio-input-microphone-symbolic", "Voice reply", self._on_mic),
            ("document-open-symbolic", "Open transcript", self._on_open),
            ("mail-reply-sender-symbolic", "Text reply", self._on_reply),
        ]:
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(14)
            btn = Gtk.Button()
            btn.set_child(img)
            btn.set_has_frame(False)
            btn.set_tooltip_text(tooltip)
            btn.add_css_class("action-btn")
            btn.connect("clicked", callback)
            box.append(btn)

        self._stack.add_named(box, "buttons")
        self._stack.set_visible_child_name("buttons")

    def _build_input_mode(self) -> None:
        """Create the text input view."""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.add_css_class("input-bar")

        # Scrolled text view
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(32)
        scrolled.set_max_content_height(160)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        vbox.append(scrolled)

        self._textview = Gtk.TextView()
        self._textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._textview.set_left_margin(8)
        self._textview.set_right_margin(8)
        self._textview.set_top_margin(6)
        self._textview.set_bottom_margin(6)
        self._textview.add_css_class("reply-input")
        scrolled.set_child(self._textview)

        # Hint
        hint = Gtk.Label(label="Enter to send \u2022 Shift+Enter for newline \u2022 Esc to go back")
        hint.add_css_class("reply-hint")
        hint.set_halign(Gtk.Align.CENTER)
        vbox.append(hint)

        # Key controller on textview for Enter handling
        tv_key = Gtk.EventControllerKey()
        tv_key.connect("key-pressed", self._on_input_key)
        self._textview.add_controller(tv_key)

        self._stack.add_named(vbox, "input")

    # -- Button callbacks --

    def _on_mic(self, btn: Gtk.Button) -> None:
        import threading
        msg = {"action": "query", "conversation_id": self._conv_id, "mic": True}
        threading.Thread(target=_send_to_daemon, args=(msg,), daemon=True).start()
        self.close()

    def _on_open(self, btn: Gtk.Button) -> None:
        import subprocess
        home = os.path.expanduser("~")
        aside_bin = os.path.join(home, ".local", "bin", "aside")
        if not os.path.isfile(aside_bin):
            aside_bin = "aside"
        subprocess.Popen([aside_bin, "open", self._conv_id])
        self.close()

    def _on_reply(self, btn: Gtk.Button) -> None:
        self._in_input_mode = True
        self._update_hold()
        Gtk4LayerShell.set_keyboard_mode(
            self, Gtk4LayerShell.KeyboardMode.ON_DEMAND
        )
        self.set_size_request(self._input_width, -1)
        self._stack.set_visible_child_name("input")
        self._textview.grab_focus()

    # -- Key handling --

    def _on_key(self, ctl: Gtk.EventControllerKey,
                keyval: int, keycode: int, state: Gdk.ModifierType) -> bool:
        if keyval == Gdk.KEY_Escape:
            # If in input mode, go back to buttons
            if self._stack.get_visible_child_name() == "input":
                self._in_input_mode = False
                self._update_hold()
                Gtk4LayerShell.set_keyboard_mode(
                    self, Gtk4LayerShell.KeyboardMode.NONE
                )
                self.set_size_request(-1, -1)
                self._stack.set_visible_child_name("buttons")
                return True
            # If in button mode, close
            self.close()
            return True
        return False

    def _on_input_key(self, ctl: Gtk.EventControllerKey,
                      keyval: int, keycode: int, state: Gdk.ModifierType) -> bool:
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if state & Gdk.ModifierType.SHIFT_MASK:
                return False  # let GTK insert newline
            self._submit()
            return True
        return False

    def _submit(self) -> None:
        buf = self._textview.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not text:
            return
        import threading
        msg = {"action": "query", "text": text, "conversation_id": self._conv_id}
        threading.Thread(target=_send_to_daemon, args=(msg,), daemon=True).start()
        self.close()


class ActionsApp(Adw.Application):
    def __init__(self, conv_id: str, width: int, margin_top: int,
                 reposition_fd: int | None = None,
                 hold_fd: int | None = None,
                 position: str = "top-center",
                 margin_left: int = 0,
                 margin_right: int = 0) -> None:
        super().__init__(application_id="dev.aside.actions")
        self._conv_id = conv_id
        self._width = width
        self._margin_top = margin_top
        self._reposition_fd = reposition_fd
        self._hold_fd = hold_fd
        self._position = position
        self._margin_left = margin_left
        self._margin_right = margin_right

    def do_activate(self) -> None:
        win = ActionsWindow(self, self._conv_id, self._width, self._margin_top,
                            reposition_fd=self._reposition_fd,
                            hold_fd=self._hold_fd,
                            position=self._position,
                            margin_left=self._margin_left,
                            margin_right=self._margin_right)
        win.present()


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser()
    parser.add_argument("--conv-id", required=True)
    parser.add_argument("--width", type=int, default=600)
    parser.add_argument("--margin-top", type=int, default=60)
    parser.add_argument("--position", default="top-center")
    parser.add_argument("--margin-left", type=int, default=0)
    parser.add_argument("--margin-right", type=int, default=0)
    parser.add_argument("--reposition-fd", type=int, default=None)
    parser.add_argument("--hold-fd", type=int, default=None)
    args = parser.parse_args()
    app = ActionsApp(args.conv_id, args.width, args.margin_top,
                     reposition_fd=args.reposition_fd,
                     hold_fd=args.hold_fd,
                     position=args.position,
                     margin_left=args.margin_left,
                     margin_right=args.margin_right)
    app.run([])


if __name__ == "__main__":
    main()
