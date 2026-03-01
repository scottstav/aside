"""GTK4 layer-shell reply window for aside overlay.

Text input box that appears below the overlay for follow-up queries.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import socket
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


def _rgb(color: str) -> str:
    """Return '#RRGGBB' from '#RRGGBB' or '#RRGGBBAA'."""
    if len(color) == 9:  # #RRGGBBAA
        return color[:7]
    return color


def _build_css(colors: dict) -> str:
    bg = _rgb(colors.get("background", "#1a1b26"))
    fg = _rgb(colors.get("foreground", "#c0caf5"))
    accent = _rgb(colors.get("accent", "#7aa2f7"))
    border = _rgb(colors.get("border", "#414868"))

    return f"""
window {{
    background-color: transparent;
}}
window.background {{
    background-color: transparent;
}}
.input-bar {{
    background-color: alpha({bg}, 0.95);
    border-radius: 12px;
    border: 1px solid alpha({accent}, 0.3);
    padding: 4px;
}}
.reply-input {{
    background-color: alpha({fg}, 0.04);
    border-radius: 6px;
    border: 1px solid alpha({border}, 0.5);
    padding: 8px;
    caret-color: {accent};
    color: {fg};
}}
.reply-input:focus {{
    border-color: {accent};
    box-shadow: 0 0 0 1px alpha({accent}, 0.3);
}}
.reply-hint {{
    font-size: 0.8em;
    color: alpha({fg}, 0.4);
    margin-top: 2px;
}}
"""


class ReplyWindow(Gtk.Window):
    """Layer-shell reply input that appears below the overlay."""

    def __init__(self, app: Adw.Application, conv_id: str,
                 width: int, margin_top: int,
                 reposition_fd: int | None = None,
                 hold_fd: int | None = None,
                 position: str = "top-center",
                 margin_left: int = 0,
                 margin_right: int = 0,
                 colors: dict | None = None) -> None:
        super().__init__(application=app)
        self._conv_id = conv_id
        self._input_width = width
        self._hold_fd = hold_fd
        self._holding = False

        # Determine which vertical edge to anchor/margin on
        self._bottom_anchored = "bottom" in position

        self.set_title("aside-reply")
        self.set_decorated(False)
        self.set_resizable(False)

        # Layer shell setup — match overlay anchoring
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)

        if self._bottom_anchored:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.BOTTOM, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.BOTTOM, margin_top)
        else:
            # top-*, center, or fallback — all use TOP anchor
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
            self, Gtk4LayerShell.KeyboardMode.ON_DEMAND
        )
        Gtk4LayerShell.set_namespace(self, "aside-reply")

        # CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(_build_css(colors or {}))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Build UI — input is the only mode
        self._build_input_mode()
        self.set_size_request(self._input_width, -1)

        # Keyboard shortcuts
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)

        # Watch for reposition messages from overlay (pipe fd)
        if reposition_fd is not None:
            threading.Thread(
                target=self._watch_reposition, args=(reposition_fd,),
                daemon=True,
            ).start()

        # Signal hold immediately — we always have keyboard focus
        self._update_hold()

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
        edge = Gtk4LayerShell.Edge.BOTTOM if self._bottom_anchored else Gtk4LayerShell.Edge.TOP
        Gtk4LayerShell.set_margin(self, edge, margin)
        return False

    # -- Hold signalling to overlay --

    def _send_hold(self, hold: bool) -> None:
        if self._hold_fd is not None:
            try:
                os.write(self._hold_fd, b"H" if hold else b"R")
            except OSError:
                pass

    def _update_hold(self) -> None:
        if not self._holding:
            self._holding = True
            self._send_hold(True)

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
        hint = Gtk.Label(label="Enter to send \u2022 Shift+Enter for newline \u2022 Esc to close")
        hint.add_css_class("reply-hint")
        hint.set_halign(Gtk.Align.CENTER)
        vbox.append(hint)

        # Key controller on textview for Enter handling
        tv_key = Gtk.EventControllerKey()
        tv_key.connect("key-pressed", self._on_input_key)
        self._textview.add_controller(tv_key)

        self.set_child(vbox)

    # -- Key handling --

    def _on_key(self, ctl: Gtk.EventControllerKey,
                keyval: int, keycode: int, state: Gdk.ModifierType) -> bool:
        if keyval == Gdk.KEY_Escape:
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


class ReplyApp(Adw.Application):
    def __init__(self, conv_id: str, width: int, margin_top: int,
                 reposition_fd: int | None = None,
                 hold_fd: int | None = None,
                 position: str = "top-center",
                 margin_left: int = 0,
                 margin_right: int = 0) -> None:
        super().__init__(application_id="dev.aside.reply")
        self._conv_id = conv_id
        self._width = width
        self._margin_top = margin_top
        self._reposition_fd = reposition_fd
        self._hold_fd = hold_fd
        self._position = position
        self._margin_left = margin_left
        self._margin_right = margin_right

    def do_activate(self) -> None:
        cfg = load_config()
        colors = cfg.get("overlay", {}).get("colors", {})
        win = ReplyWindow(self, self._conv_id, self._width, self._margin_top,
                          reposition_fd=self._reposition_fd,
                          hold_fd=self._hold_fd,
                          position=self._position,
                          margin_left=self._margin_left,
                          margin_right=self._margin_right,
                          colors=colors)
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
    parser.add_argument("--margin-bottom", type=int, default=0)
    parser.add_argument("--reposition-fd", type=int, default=None)
    parser.add_argument("--hold-fd", type=int, default=None)
    args = parser.parse_args()
    app = ReplyApp(args.conv_id, args.width, args.margin_top,
                   reposition_fd=args.reposition_fd,
                   hold_fd=args.hold_fd,
                   position=args.position,
                   margin_left=args.margin_left,
                   margin_right=args.margin_right)
    app.run([])


if __name__ == "__main__":
    main()
