"""GTK4 overlay application — socket listener + main entry point."""

from __future__ import annotations

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

# Workaround: distros that don't package gtk4-layer-shell (Ubuntu/Debian as of
# 24.04) require building it from source, which installs typelibs to
# /usr/local/lib/... — a path gi doesn't search by default.  Distros with a
# native package (Arch, Fedora 40+, openSUSE TW) don't need this.
# Remove once gtk4-layer-shell lands in Ubuntu's repos.
_EXTRA_TYPELIB_DIRS = [
    "/usr/local/lib/girepository-1.0",
    "/usr/local/lib/x86_64-linux-gnu/girepository-1.0",
    "/usr/local/lib/aarch64-linux-gnu/girepository-1.0",
]
_gi_path = os.environ.get("GI_TYPELIB_PATH", "")
_extra = os.pathsep.join(d for d in _EXTRA_TYPELIB_DIRS if os.path.isdir(d))
if _extra:
    os.environ["GI_TYPELIB_PATH"] = f"{_gi_path}{os.pathsep}{_extra}" if _gi_path else _extra

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Adw, GLib

from aside.config import load_config, resolve_socket_path

log = logging.getLogger(__name__)


def parse_command(line: str) -> dict | None:
    """Parse a JSON command line. Returns None on invalid input."""
    if not line.strip():
        return None
    try:
        return json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None


class OverlayApp(Adw.Application):
    """Main overlay application — manages window and socket listener."""

    def __init__(self) -> None:
        super().__init__(application_id="dev.aside.overlay")
        self._config = load_config()
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)

    def do_activate(self) -> None:
        from aside.overlay.window import OverlayWindow
        self._window = OverlayWindow(self, self._config)
        # Don't present — window starts hidden
        threading.Thread(target=self._listen_socket, daemon=True).start()

    def _listen_socket(self) -> None:
        """Listen on aside-overlay.sock for commands from the daemon."""
        sock_path = resolve_socket_path("aside-overlay.sock")
        try:
            os.unlink(str(sock_path))
        except FileNotFoundError:
            pass

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        os.chmod(str(sock_path), 0o600)
        server.listen(5)
        log.info("Overlay listening on %s", sock_path)

        while True:
            conn, _ = server.accept()
            threading.Thread(
                target=self._handle_connection,
                args=(conn,),
                daemon=True,
            ).start()

    def _handle_connection(self, conn: socket.socket) -> None:
        """Read newline-delimited JSON commands from a connection."""
        buf = b""
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    cmd = parse_command(line.decode("utf-8", errors="replace"))
                    if cmd:
                        GLib.idle_add(self._dispatch, cmd)
            # Handle remaining data without newline
            if buf.strip():
                cmd = parse_command(buf.decode("utf-8", errors="replace"))
                if cmd:
                    GLib.idle_add(self._dispatch, cmd)
        except OSError:
            pass
        finally:
            conn.close()

    def _dispatch(self, cmd: dict) -> bool:
        """Dispatch a command to the overlay window. Runs on GTK main thread."""
        name = cmd.get("cmd", "")
        if name == "open":
            self._window.handle_open(cmd.get("mode", "user"), cmd.get("conv_id", ""))
        elif name == "text":
            self._window.handle_text(cmd.get("data", ""))
        elif name == "done":
            self._window.handle_done()
        elif name == "clear":
            self._window.handle_clear()
        elif name == "replace":
            self._window.handle_replace(cmd.get("data", ""))
        elif name == "thinking":
            self._window.handle_thinking()
        elif name == "listening":
            self._window.handle_listening()
        elif name == "input":
            self._window.handle_input()
        elif name in ("reply", "convo"):
            self._window.handle_convo(cmd.get("conversation_id", ""))
        return False  # remove from idle queue


def main() -> None:
    """Entry point for aside-overlay."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    app = OverlayApp()
    app.run([])
