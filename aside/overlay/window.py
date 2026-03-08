"""Main overlay window with state machine and view switching."""

from __future__ import annotations

import enum
import json
import logging
import socket
import threading

import gi
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell

from aside.config import load_config, resolve_conversations_dir, resolve_socket_path
from aside.overlay.accent_bar import AccentBar, BarState
from aside.overlay.conversation import ConversationHistory
from aside.overlay.css import build_css
from aside.overlay.picker import ConversationPicker
from aside.overlay.reply_input import ReplyInput

log = logging.getLogger(__name__)


class OverlayState(enum.Enum):
    HIDDEN = "hidden"
    STREAMING = "streaming"
    DISPLAY = "display"
    CONVO = "convo"
    PICKER = "picker"


class OverlayWindow(Gtk.Window):
    def __init__(self, app, config: dict):
        super().__init__(application=app)
        self._config = config
        self._state = OverlayState.HIDDEN
        self._conv_id: str | None = None
        self._accumulated_text = ""
        self._dismiss_timer_id: int | None = None

        overlay_cfg = config.get("overlay", {})
        colors = overlay_cfg.get("colors", {})
        self._markdown_enabled = overlay_cfg.get("markdown", True)

        # Window setup
        self.set_title("aside")
        self.set_decorated(False)
        self.set_resizable(False)
        width = overlay_cfg.get("width", 600)
        self.set_default_size(width, -1)

        # Layer-shell setup
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.ON_DEMAND)
        Gtk4LayerShell.set_namespace(self, "aside")

        # Anchoring from config
        position = overlay_cfg.get("position", "top-center")
        margin_top = overlay_cfg.get("margin_top", 10)
        margin_left = overlay_cfg.get("margin_left", 0)
        margin_right = overlay_cfg.get("margin_right", 0)

        if "bottom" in position:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.BOTTOM, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.BOTTOM, margin_top)
        else:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, margin_top)

        if "left" in position:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.LEFT, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.LEFT, margin_left)
        elif "right" in position:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.RIGHT, margin_right)

        # CSS
        accent_color = colors.get("accent", "#7aa2f7ff")
        font = overlay_cfg.get("font", "")
        css_text = build_css(colors, font=font)
        provider = Gtk.CssProvider()
        provider.load_from_string(css_text)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Build widget tree
        self._main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._main_box.add_css_class("overlay-container")
        self.set_child(self._main_box)

        # Accent bar (always visible, outside stack)
        self._accent_bar = AccentBar(accent_color=accent_color, corner_radius=12)
        self._main_box.append(self._accent_bar)

        # Stack for view switching
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)
        self._main_box.append(self._stack)

        # --- Stream view ---
        stream_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._stream_history = ConversationHistory(markdown=self._markdown_enabled)
        self._stream_history.set_vexpand(True)
        stream_box.append(self._stream_history)
        # Action buttons
        self._action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._action_bar.add_css_class("action-bar")
        self._action_bar.set_halign(Gtk.Align.CENTER)
        self._action_bar.set_margin_top(8)
        self._action_bar.set_margin_bottom(8)
        self._action_bar.set_visible(False)

        reply_btn = Gtk.Button(label="Reply")
        reply_btn.connect("clicked", self._on_reply_clicked)
        self._action_bar.append(reply_btn)

        stream_box.append(self._action_bar)
        self._stack.add_named(stream_box, "stream")

        # --- Convo view ---
        convo_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._convo_history = ConversationHistory(markdown=self._markdown_enabled)
        self._convo_history.set_vexpand(True)
        convo_box.append(self._convo_history)
        self._convo_reply = ReplyInput()
        self._convo_reply.connect_submit(self._on_submit)
        convo_box.append(self._convo_reply)
        self._stack.add_named(convo_box, "convo")

        # --- Picker view ---
        self._picker = ConversationPicker()
        self._picker.connect_submit(self._on_picker_submit)
        self._stack.add_named(self._picker, "picker")

        # Keyboard controller
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)

        # Mouse click controller
        click = Gtk.GestureClick()
        click.set_button(0)  # all buttons
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        # Start hidden
        self.set_visible(False)

    @property
    def state(self) -> OverlayState:
        return self._state

    def _set_state(self, state: OverlayState) -> None:
        self._state = state
        # Update keyboard mode based on state
        if state in (OverlayState.CONVO, OverlayState.PICKER):
            Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.ON_DEMAND)
        else:
            Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.NONE)

    # --- Socket command handlers ---

    def handle_open(self, mode: str = "user", conv_id: str = "") -> None:
        """HIDDEN->STREAMING: show overlay, start streaming."""
        self._conv_id = conv_id or None
        self._accumulated_text = ""
        self._stream_history.clear()
        self._stream_history.add_message("assistant", "")
        self._action_bar.set_visible(False)
        self._stack.set_visible_child_name("stream")
        self._accent_bar.set_state(BarState.STREAMING)
        self._set_state(OverlayState.STREAMING)
        self.set_visible(True)

    def handle_text(self, data: str) -> None:
        """Append streamed text to current message."""
        self._accumulated_text += data
        self._stream_history.update_last_message(self._accumulated_text)

    def handle_done(self) -> None:
        """STREAMING->DISPLAY: show action buttons, start dismiss timer."""
        self._accent_bar.set_state(BarState.IDLE)
        self._action_bar.set_visible(True)
        self._set_state(OverlayState.DISPLAY)
        self._start_dismiss_timer()

    def handle_clear(self) -> None:
        """Any->HIDDEN: hide overlay."""
        self._cancel_dismiss_timer()
        self.set_visible(False)
        self._accent_bar.set_state(BarState.IDLE)
        self._set_state(OverlayState.HIDDEN)

    def handle_replace(self, data: str) -> None:
        """Replace all text in current message."""
        self._accumulated_text = data
        self._stream_history.update_last_message(data)

    def handle_thinking(self) -> None:
        """Set accent bar to thinking animation."""
        self._accent_bar.set_state(BarState.THINKING)

    def handle_listening(self) -> None:
        """Set accent bar to listening animation."""
        self._accent_bar.set_state(BarState.LISTENING)

    def handle_input(self) -> None:
        """Any->PICKER: show conversation picker."""
        self._cancel_dismiss_timer()
        from aside.state import ConversationStore
        conv_dir = resolve_conversations_dir(self._config)
        entries = []
        try:
            if conv_dir.is_dir():
                store = ConversationStore(conv_dir)
                entries = store.list_recent(limit=15)
        except Exception:
            log.exception("Failed to load conversations")
        self._picker.populate(entries)
        self._stack.set_visible_child_name("picker")
        self._accent_bar.set_state(BarState.IDLE)
        self._set_state(OverlayState.PICKER)
        self.set_visible(True)
        self._picker.focus_input()

    def handle_convo(self, conv_id: str) -> None:
        """Any->CONVO: view a conversation."""
        self._load_convo(conv_id)

    def _load_convo(self, conv_id: str) -> None:
        """Load conversation history into convo view."""
        self._cancel_dismiss_timer()
        from aside.state import ConversationStore
        conv_dir = resolve_conversations_dir(self._config)
        store = ConversationStore(conv_dir)
        conv = store.get_or_create(conv_id)
        self._conv_id = conv_id
        self._convo_history.load_conversation(conv)
        self._convo_reply.clear()
        self._stack.set_visible_child_name("convo")
        self._accent_bar.set_state(BarState.IDLE)
        self._set_state(OverlayState.CONVO)
        self.set_visible(True)

    # --- Dismiss timer ---

    def _start_dismiss_timer(self, seconds: float = 5.0) -> None:
        self._cancel_dismiss_timer()
        self._dismiss_timer_id = GLib.timeout_add(
            int(seconds * 1000), self._on_dismiss_timeout
        )

    def _cancel_dismiss_timer(self) -> None:
        if self._dismiss_timer_id is not None:
            GLib.source_remove(self._dismiss_timer_id)
            self._dismiss_timer_id = None

    def _on_dismiss_timeout(self) -> bool:
        self._dismiss_timer_id = None
        if self._state == OverlayState.DISPLAY:
            self.handle_clear()
        return False  # don't repeat

    # --- User action handlers ---

    def _on_click(self, gesture, n_press, x, y) -> None:
        """Handle mouse clicks: left=dismiss, middle=stop TTS, right=cancel."""
        button = gesture.get_current_button()
        if button == 1:  # left click
            if self._state == OverlayState.DISPLAY:
                self.handle_clear()
        elif button == 2:  # middle click — stop TTS
            msg = {"action": "stop_tts"}
            threading.Thread(
                target=self._send_to_daemon, args=(msg,), daemon=True
            ).start()
        elif button == 3:  # right click — cancel query + TTS
            msg = {"action": "cancel"}
            threading.Thread(
                target=self._send_to_daemon, args=(msg,), daemon=True
            ).start()
            self.handle_clear()

    def _on_reply_clicked(self, button) -> None:
        """DISPLAY->CONVO: load full conversation view."""
        self._cancel_dismiss_timer()
        if self._conv_id:
            self._load_convo(self._conv_id)

    def _on_submit(self, text: str) -> None:
        """Send query to daemon when user submits from reply input."""
        if not text.strip():
            return
        msg = {
            "action": "query",
            "text": text.strip(),
            "conversation_id": self._conv_id,
        }
        threading.Thread(
            target=self._send_to_daemon, args=(msg,), daemon=True
        ).start()

    def _on_picker_submit(self, text: str, conv_id: str) -> None:
        """Send query from picker."""
        if not text.strip():
            return
        msg = {
            "action": "query",
            "text": text.strip(),
            "conversation_id": conv_id if conv_id != "__new__" else "__new__",
        }
        threading.Thread(
            target=self._send_to_daemon, args=(msg,), daemon=True
        ).start()

    def _send_to_daemon(self, msg: dict) -> None:
        """Send JSON message to the daemon socket."""
        sock_path = resolve_socket_path()
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(str(sock_path))
            s.sendall((json.dumps(msg) + "\n").encode())
            s.close()
        except OSError:
            log.exception("Failed to send to daemon at %s", sock_path)

    def _on_key(self, ctl, keyval, keycode, state) -> bool:
        """Window-level keyboard handler."""
        self._cancel_dismiss_timer()
        if keyval == Gdk.KEY_Escape:
            self.handle_clear()
            return True
        return False
