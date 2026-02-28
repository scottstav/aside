# GTK4 Action Bar Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the C overlay's hand-rolled buttons and text input with a GTK4 layer-shell popup (`aside-actions`) that appears below the overlay after a response completes.

**Architecture:** The C overlay becomes a pure text renderer. On CMD_DONE, it spawns `aside-actions` — a Python GTK4 + gtk4-layer-shell app that renders action buttons (mic, open, reply) and transitions to a full-featured text input when "reply" is clicked. The GTK popup sends actions directly to the daemon socket and closes itself.

**Tech Stack:** Python 3, GTK4, gtk4-layer-shell, Adwaita (for CSS/theming consistency)

---

### Task 1: Create aside-actions Python entry point

**Files:**
- Create: `aside/actions/__init__.py`
- Create: `aside/actions/window.py`
- Modify: `pyproject.toml` — add `aside-actions` console script

**Step 1: Create the package skeleton**

`aside/actions/__init__.py`:
```python
```

`aside/actions/window.py`:
```python
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
    """Send a JSON message to the aside daemon."""
    sock_path = resolve_socket_path()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(sock_path))
        s.sendall((json.dumps(msg) + "\n").encode())
        s.close()
    except OSError:
        log.exception("Failed to send to daemon")


CSS = """
window {
    background-color: transparent;
}
.action-bar {
    background-color: alpha(@window_bg_color, 0.95);
    border-radius: 8px;
    border: 1px solid alpha(@accent_color, 0.3);
    padding: 6px;
}
.action-btn {
    border-radius: 6px;
    padding: 6px 16px;
    min-height: 28px;
    background: alpha(@window_fg_color, 0.06);
    border: 1px solid alpha(@accent_color, 0.2);
    color: @accent_color;
    font-weight: 500;
}
.action-btn:hover {
    background: alpha(@accent_color, 0.15);
    border-color: alpha(@accent_color, 0.5);
}
.action-btn:active {
    background: alpha(@accent_color, 0.25);
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
    margin-top: 4px;
}
"""


class ActionsWindow(Adw.ApplicationWindow):
    """Layer-shell action bar that appears below the overlay."""

    def __init__(self, app: Adw.Application, conv_id: str,
                 width: int, margin_top: int) -> None:
        super().__init__(application=app)
        self._conv_id = conv_id

        self.set_title("aside-actions")
        self.set_default_size(width, -1)

        # Layer shell setup
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, margin_top)
        Gtk4LayerShell.set_keyboard_mode(
            self, Gtk4LayerShell.KeyboardMode.ON_DEMAND
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
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)

        self._build_button_mode()
        self._build_input_mode()
        self.set_content(self._stack)

        # Keyboard shortcuts
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)

    def _build_button_mode(self) -> None:
        """Create the action buttons view."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.add_css_class("action-bar")
        box.set_halign(Gtk.Align.CENTER)

        for label, callback in [
            ("mic", self._on_mic),
            ("open", self._on_open),
            ("reply", self._on_reply),
        ]:
            btn = Gtk.Button(label=label)
            btn.add_css_class("action-btn")
            btn.set_hexpand(True)
            btn.connect("clicked", callback)
            box.append(btn)

        self._stack.add_named(box, "buttons")
        self._stack.set_visible_child_name("buttons")

    def _build_input_mode(self) -> None:
        """Create the text input view."""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.add_css_class("action-bar")

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
        self._stack.set_visible_child_name("input")
        self._textview.grab_focus()

    # -- Key handling --

    def _on_key(self, ctl: Gtk.EventControllerKey,
                keyval: int, keycode: int, state: Gdk.ModifierType) -> bool:
        if keyval == Gdk.KEY_Escape:
            # If in input mode, go back to buttons
            if self._stack.get_visible_child_name() == "input":
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
    def __init__(self, conv_id: str, width: int, margin_top: int) -> None:
        super().__init__(application_id="dev.aside.actions")
        self._conv_id = conv_id
        self._width = width
        self._margin_top = margin_top

    def do_activate(self) -> None:
        win = ActionsWindow(self, self._conv_id, self._width, self._margin_top)
        win.present()


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser()
    parser.add_argument("--conv-id", required=True)
    parser.add_argument("--width", type=int, default=600)
    parser.add_argument("--margin-top", type=int, default=60)
    args = parser.parse_args()
    app = ActionsApp(args.conv_id, args.width, args.margin_top)
    app.run([])


if __name__ == "__main__":
    main()
```

**Step 2: Add console script to pyproject.toml**

In `pyproject.toml`, in the `[project.scripts]` section, add:
```
aside-actions = "aside.actions.window:main"
```

**Step 3: Install and verify it launches**

Run: `pip install -e .`
Run: `aside-actions --conv-id test123 --width 600 --margin-top 60`
Expected: GTK4 layer-shell window appears, shows 3 buttons. Escape closes it.

**Step 4: Commit**

```
git add aside/actions/ pyproject.toml
git commit -m "feat: add aside-actions GTK4 layer-shell action bar"
```

---

### Task 2: Strip buttons, input, and keyboard handling from C overlay

**Files:**
- Modify: `overlay/src/main.c`
- Modify: `overlay/src/render.c`
- Modify: `overlay/src/render.h`
- Modify: `overlay/src/wayland.c`
- Modify: `overlay/src/wayland.h`
- Modify: `overlay/meson.build`

**Step 1: Remove button/input state from main.c**

Remove these globals:
- `enum overlay_button` and `BTN_ACTION_COUNT`
- `action_buttons[]` array
- `show_buttons` flag
- `input_active`, `input_buf`, `input_len`
- `button_row_height`

Remove these functions entirely:
- `handle_button_click()` (lines 115-153)
- `on_key()` (lines 156-207)

In `dismiss_overlay()`: remove lines that touch `show_buttons`, `input_active`, `input_len`.

Remove `button_row_height` initialization (line ~250).

Remove keyboard callback wiring: `state.key_cb = on_key;` and `state.key_cb_data = &state;`

**Step 2: Remove button hit-testing from pointer handler**

In the pointer button click handler (around line 442-461), remove the entire `if (show_buttons) { for ... handle_button_click ... }` block. Keep the left-click dismiss and right-click cancel logic.

**Step 3: Update CMD_DONE to spawn aside-actions**

Replace the current CMD_DONE handler's `show_buttons = true` and height+button_row adjustment with:

```c
case CMD_DONE: {
    /* Spawn GTK action bar below overlay */
    int content_h = renderer_measure(&rend, &cfg, text_buf);
    uint32_t max_h = cfg.padding_y * 2 + (uint32_t)rend.line_height * cfg.max_lines;
    uint32_t target_h = (uint32_t)content_h + cfg.padding_y * 2;
    if (target_h > max_h) target_h = max_h;
    uint32_t min_h = cfg.padding_y * 2 + (uint32_t)rend.line_height;
    if (target_h < min_h) target_h = min_h;

    if (target_h != state.height && state.layer_surface) {
        zwlr_layer_surface_v1_set_size(state.layer_surface,
                                        cfg.width, target_h);
        wl_surface_commit(state.surface);
        state.height = target_h;
    }

    /* Launch aside-actions positioned below this overlay */
    if (current_conv_id[0] != '\0') {
        char margin_str[32], width_str[32];
        snprintf(margin_str, sizeof(margin_str), "%u",
                 cfg.margin_top + state.height + 4);
        snprintf(width_str, sizeof(width_str), "%u", cfg.width);

        const char *home = getenv("HOME");
        char bin[512] = "aside-actions";
        if (home) {
            snprintf(bin, sizeof(bin), "%s/.local/bin/aside-actions", home);
            if (access(bin, X_OK) != 0)
                snprintf(bin, sizeof(bin), "aside-actions");
        }

        if (fork() == 0) {
            execl(bin, "aside-actions",
                  "--conv-id", current_conv_id,
                  "--width", width_str,
                  "--margin-top", margin_str,
                  NULL);
            _exit(1);
        }
    }

    state.needs_redraw = true;
    done_at = anim_now_ms();
    break;
}
```

**Step 4: Remove show_buttons/input_active resets from CMD_OPEN, CMD_TEXT, CMD_CLEAR**

In CMD_OPEN, CMD_TEXT, CMD_CLEAR handlers, remove lines like:
```c
show_buttons = false;
input_active = false;
```

**Step 5: Simplify renderer_draw() call**

Update the call in the redraw section to remove button/input args:
```c
renderer_draw(&rend, &cfg, state.pixels,
              state.configured_width * s, state.configured_height * s,
              text_buf, scroll_anim.current, fade_anim.current);
```

**Step 6: Simplify render.c**

Remove `draw_buttons()` and `draw_input_box()` functions entirely.

Remove `struct button_rect` from `render.h`.

Update `renderer_draw()` signature to just:
```c
void renderer_draw(struct renderer *r, const struct overlay_config *cfg,
                   uint8_t *pixels, int buf_w, int buf_h,
                   const char *text, double scroll_y, double fade_alpha);
```

Remove the conditional button/input rendering block and the `bottom_row` height reservation.

**Step 7: Remove xkbcommon from overlay**

In `wayland.c`: remove keyboard listener functions (`keyboard_keymap`, `keyboard_key`, `keyboard_modifiers`, `keyboard_enter`, `keyboard_leave`, `keyboard_repeat_info`), the `wl_keyboard_listener`, and the keyboard binding in `seat_capabilities`. Remove xkb teardown from `wayland_cleanup`.

In `wayland.h`: remove `struct wl_keyboard *keyboard`, `struct xkb_context/xkb_keymap/xkb_state`, `keyboard_key_cb`, `key_cb`, `key_cb_data`.

In `meson.build`: remove `dep_xkbcommon`.

Also remove `zwlr_layer_surface_v1_set_keyboard_interactivity()` call from `wayland_create_surface()` since the overlay no longer needs keyboard focus.

**Step 8: Build and verify**

Run: `cd overlay && ninja -C build`
Expected: Clean compile, no warnings about removed variables.

**Step 9: Commit**

```
git add overlay/
git commit -m "refactor: strip buttons, input, and keyboard from C overlay

The C overlay is now a pure text renderer. All interaction
(action buttons + text input) moves to aside-actions GTK popup."
```

---

### Task 3: VM integration test

**Step 1: Push and deploy**

```bash
git push
# In VM:
cd /tmp/aside && git pull
pip install -e . --break-system-packages
cd overlay && ninja -C build && sudo cp build/aside-overlay /usr/bin/
```

**Step 2: Install GTK4 layer-shell in VM**

```bash
sudo pacman -S gtk4-layer-shell --noconfirm
```

**Step 3: Restart services and test**

```bash
killall aside-overlay python3
# Start overlay and daemon
nohup aside-overlay > /tmp/aside-overlay.log 2>&1 & disown
nohup python3 -m aside.daemon > /tmp/aside-daemon.log 2>&1 & disown
# Send a query
aside query "Say hello"
```

Expected:
1. Overlay streams "Hello!" text
2. After CMD_DONE, GTK action bar appears below overlay with [mic] [open] [reply]
3. Clicking reply transitions to text input with blinking cursor, word wrapping
4. Typing text, pressing Enter submits and closes GTK popup
5. Overlay gets new response

**Step 4: Verify button actions**

- Click "open" → `aside open` runs, transcript prints
- Click "mic" → sends mic:true to daemon
- Click "reply" → transitions to input, Escape goes back to buttons, double-Escape closes

**Step 5: Commit any fixes**

```
git commit -am "fix: integration fixes for aside-actions"
```
