"""Main overlay window with state machine and view switching."""

from __future__ import annotations

import enum
import json
import logging
import math
import socket
import threading

import gi
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell

from aside.config import resolve_conversations_dir, resolve_socket_path
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
        self._thinking_tick_id: int | None = None
        self._thinking_dots: int = 0
        self._thinking_base_text: str = ""

        overlay_cfg = config.get("overlay", {})
        self._dismiss_timeout: float = overlay_cfg.get("dismiss_timeout", 5.0)
        colors = overlay_cfg.get("colors", {})
        self._markdown_enabled = overlay_cfg.get("markdown", True)

        # Dimensions
        width = overlay_cfg.get("width", 400)
        self._default_width = width
        max_height = overlay_cfg.get("max_height", 500)
        self.set_title("aside")
        self.set_decorated(False)
        self.set_size_request(width, -1)

        # Layer-shell setup
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
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
        accent_color = colors.get("accent", "#8b5cf6")
        user_accent_color = colors.get("user_accent", "#22d3ee")
        font = overlay_cfg.get("font", "")
        opacity = overlay_cfg.get("opacity", 0.95)
        css_text = build_css(colors, font=font, opacity=opacity)
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
        self._accent_bar = AccentBar(
            accent_color=accent_color,
            user_accent_color=user_accent_color,
            corner_radius=12,
        )
        self._main_box.append(self._accent_bar)

        # Stack for view switching
        self._stack = Gtk.Stack()
        self._stack.set_vhomogeneous(False)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)
        self._main_box.append(self._stack)

        # --- Stream view ---
        self._max_height = max_height
        self._current_window_h = 0
        stream_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._stream_box = stream_box
        self._stream_history = ConversationHistory(markdown=self._markdown_enabled)
        # Let ScrolledWindow report its content height so parent measure() is accurate
        self._stream_history.set_propagate_natural_height(True)
        self._stream_history.set_max_content_height(max_height)
        stream_box.append(self._stream_history)

        # Window controls its own height based on content
        vadj = self._stream_history.get_vadjustment()
        if vadj is not None:
            vadj.connect("changed", self._on_stream_content_changed)
        # Action buttons (icon-only: mic, copy, reply)
        self._action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._action_bar.add_css_class("action-bar")
        self._action_bar.set_halign(Gtk.Align.CENTER)
        self._action_bar.set_margin_top(8)
        self._action_bar.set_margin_bottom(8)
        self._action_bar.set_visible(False)

        mic_btn = Gtk.Button.new_from_icon_name("audio-input-microphone-symbolic")
        mic_btn.set_tooltip_text("Voice reply")
        mic_btn.add_css_class("action-icon")
        mic_btn.connect("clicked", self._on_mic_reply_clicked)
        self._action_bar.append(mic_btn)

        open_btn = Gtk.Button.new_from_icon_name("document-open-symbolic")
        open_btn.set_tooltip_text("Open transcript")
        open_btn.add_css_class("action-icon")
        open_btn.connect("clicked", self._on_open_clicked)
        self._action_bar.append(open_btn)

        reply_btn = Gtk.Button.new_from_icon_name("mail-reply-sender-symbolic")
        reply_btn.set_tooltip_text("Reply")
        reply_btn.add_css_class("action-icon")
        reply_btn.connect("clicked", self._on_reply_clicked)
        self._action_bar.append(reply_btn)

        stream_box.append(self._action_bar)
        # Inline reply input (hidden until Reply is clicked)
        self._stream_reply = ReplyInput()
        self._stream_reply.connect_submit(self._on_stream_reply_submit)
        self._stream_reply.connect_expand(self._on_expand_convo)
        self._stream_reply.set_visible(False)
        stream_box.append(self._stream_reply)
        self._stack.add_named(stream_box, "stream")

        # --- Convo view ---
        convo_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._convo_history = ConversationHistory(markdown=self._markdown_enabled)
        self._convo_history.set_max_content_height(max_height)
        convo_box.append(self._convo_history)
        self._convo_reply = ReplyInput()
        self._convo_reply.connect_submit(self._on_submit)
        self._convo_reply.connect_expand(self._on_expand_convo)
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

        # Hover pauses auto-dismiss (without stealing focus)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_hover_enter)
        motion.connect("leave", self._on_hover_leave)
        self.add_controller(motion)

        # Start hidden
        self.set_visible(False)

    @property
    def state(self) -> OverlayState:
        return self._state

    def _set_state(self, state: OverlayState) -> None:
        self._state = state
        # EXCLUSIVE: grab keyboard for interactive states (picker, convo, reply)
        # ON_DEMAND: receive pointer events (hover) without stealing keyboard focus
        if state in (OverlayState.CONVO, OverlayState.PICKER):
            Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
        else:
            Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.ON_DEMAND)

    # --- Socket command handlers ---

    def handle_open(self, mode: str = "user", conv_id: str = "") -> None:
        """HIDDEN->STREAMING: show overlay, start streaming."""
        self._stop_thinking_dots()
        self._conv_id = conv_id or None
        self._accumulated_text = ""
        self._stream_history.clear()
        self._stream_history.add_message(mode, "")
        self._action_bar.set_visible(True)
        self._stream_reply.set_visible(False)
        self._stack.set_visible_child_name("stream")
        self._accent_bar.set_state(BarState.STREAMING)
        self._set_state(OverlayState.STREAMING)
        self.set_visible(True)

    def handle_stream_start(self) -> None:
        """Transition from user text to assistant streaming without clearing.

        Used after mic capture: keeps the user's transcribed text visible
        and adds a new assistant message for the LLM response.
        """
        self._stop_thinking_dots()
        if self._accumulated_text:
            self._stream_history.update_last_message(self._accumulated_text)
        self._accumulated_text = ""
        self._stream_history.add_message("assistant", "")
        self._accent_bar.set_state(BarState.STREAMING)
        self._set_state(OverlayState.STREAMING)

    def handle_text(self, data: str) -> None:
        """Append streamed text to current message."""
        self._stop_thinking_dots()
        self._accumulated_text += data
        self._stream_history.update_last_message(self._accumulated_text)

    def handle_done(self) -> None:
        """STREAMING->DISPLAY: start dismiss timer."""
        self._accent_bar.set_state(BarState.IDLE)
        self._set_state(OverlayState.DISPLAY)
        self._start_dismiss_timer(self._dismiss_timeout)

    def handle_clear(self) -> None:
        """Any->HIDDEN: hide overlay."""
        self._cancel_dismiss_timer()
        self._stop_thinking_dots()
        self.set_visible(False)
        self._current_window_h = 0
        self.set_size_request(self._default_width, -1)
        self._accent_bar.set_state(BarState.IDLE)
        self._set_state(OverlayState.HIDDEN)

    def handle_replace(self, data: str) -> None:
        """Replace all text in current message."""
        self._stop_thinking_dots()
        self._accumulated_text = data
        self._stream_history.update_last_message(data)

    def handle_thinking(self) -> None:
        """Set accent bar to thinking animation and show animated dots."""
        self._accent_bar.set_state(BarState.THINKING)
        self._thinking_dots = 0
        self._thinking_base_text = self._accumulated_text.rstrip()
        self._stop_thinking_dots()
        self._thinking_tick_id = GLib.timeout_add(400, self._on_thinking_tick)

    def _on_thinking_tick(self) -> bool:
        """Cycle dots appended to current text."""
        self._thinking_dots = (self._thinking_dots % 3) + 1
        dots = " " + "." * self._thinking_dots if self._thinking_base_text else "." * self._thinking_dots
        self._stream_history.update_last_message(self._thinking_base_text + dots)
        return True  # keep repeating

    def _stop_thinking_dots(self) -> None:
        if self._thinking_tick_id is not None:
            GLib.source_remove(self._thinking_tick_id)
            self._thinking_tick_id = None

    def handle_listening(self) -> None:
        """Set accent bar to listening animation."""
        self._accent_bar.set_state(BarState.LISTENING)

    def handle_audio_level(self, level: float) -> None:
        """Push an audio level to the waveform visualizer."""
        self._accent_bar.push_audio_level(level)

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
        self._picker.clear_input()
        self._stack.set_visible_child_name("picker")
        self._accent_bar.set_state(BarState.IDLE)
        self._set_state(OverlayState.PICKER)
        self.set_visible(True)
        self._picker.focus_input()

    def handle_convo(self, conv_id: str | None = None) -> None:
        """Any->CONVO: view a conversation. None = current or most recent."""
        if not conv_id:
            if self._conv_id:
                conv_id = self._conv_id
            else:
                from aside.state import ConversationStore
                conv_dir = resolve_conversations_dir(self._config)
                store = ConversationStore(conv_dir)
                conv_id = store.resolve_last()
                if not conv_id:
                    return
        self._load_convo(conv_id)

    def _load_convo(self, conv_id: str) -> None:
        """Load conversation history into convo view."""
        self._cancel_dismiss_timer()
        # If we're already showing this conversation, load from disk
        # but skip reload if we have in-memory state (avoids stale-file race)
        already_showing = (
            self._conv_id == conv_id
            and self._state in (OverlayState.STREAMING, OverlayState.DISPLAY)
        )
        if not already_showing:
            from aside.state import ConversationStore
            conv_dir = resolve_conversations_dir(self._config)
            store = ConversationStore(conv_dir)
            conv = store.get_or_create(conv_id)
            self._convo_history.load_conversation(conv)
        else:
            # Copy messages from stream view into convo view
            self._convo_history.clear()
            for mv in self._stream_history._messages:
                self._convo_history.add_message(mv.role, mv.get_raw_text())
        self._conv_id = conv_id
        self._convo_reply.clear()
        self._stack.set_visible_child_name("convo")
        self._accent_bar.set_state(BarState.IDLE)
        self._set_state(OverlayState.CONVO)
        self.set_visible(True)
        self._convo_reply.focus_input()

    # --- Window sizing ---

    def _on_stream_content_changed(self, vadj) -> None:
        """Resize window to fit content, capped at max_height.

        With propagate_natural_height on the ScrolledWindow, main_box.measure()
        returns the true total including all children, margins, borders, and padding.
        """
        _, nat_h, _, _ = self._main_box.measure(
            Gtk.Orientation.VERTICAL, self._default_width
        )
        target = min(math.ceil(nat_h), self._max_height)
        if target != self._current_window_h:
            self._current_window_h = target
            self.set_size_request(self._default_width, target)

    # --- Dismiss timer ---

    def _start_dismiss_timer(self, seconds: float = 5.0) -> None:
        self._cancel_dismiss_timer()
        if seconds <= 0:
            return
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

    def _on_hover_enter(self, *_args) -> None:
        """Pause auto-dismiss while cursor is over the overlay."""
        self._cancel_dismiss_timer()

    def _on_hover_leave(self, *_args) -> None:
        """Restart auto-dismiss when cursor leaves the overlay."""
        if self._state == OverlayState.DISPLAY:
            self._start_dismiss_timer(self._dismiss_timeout)

    # --- User action handlers ---

    def _on_click(self, gesture, n_press, x, y) -> None:
        """Handle mouse clicks: left=dismiss, middle=stop TTS, right=cancel."""
        # Don't dismiss if clicking an interactive widget (e.g. Reply button)
        target = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        if target is not None and target is not self._main_box and target is not self:
            widget = target
            while widget is not None:
                if isinstance(widget, Gtk.Button):
                    return
                widget = widget.get_parent()
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

    def _on_mic_reply_clicked(self, button) -> None:
        """Start a voice reply for the current conversation."""
        conv_id = self._conv_id or ""
        msg = {"action": "query", "mic": True, "conversation_id": conv_id}
        threading.Thread(
            target=self._send_to_daemon, args=(msg,), daemon=True
        ).start()

    def _on_open_clicked(self, button) -> None:
        """Open the conversation transcript .md file in default editor."""
        if not self._conv_id:
            return
        from aside.config import resolve_conversations_dir
        from aside.state import ConversationStore
        store = ConversationStore(resolve_conversations_dir(self._config))
        path = store.transcript_path(self._conv_id)
        if path.exists():
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])

    def _on_reply_clicked(self, button) -> None:
        """Show inline reply input below the streamed response."""
        self._cancel_dismiss_timer()
        self._action_bar.set_visible(False)
        self._stream_reply.clear()
        self._stream_reply.set_visible(True)
        self._set_state(OverlayState.CONVO)
        self._stream_reply.focus_input()

    def _on_expand_convo(self) -> None:
        """Shift+Tab: expand to full conversation view."""
        if self._conv_id:
            self._load_convo(self._conv_id)

    def _on_submit(self, text: str) -> None:
        """Send query to daemon when user submits from convo reply input."""
        self._send_reply(text)

    def _on_stream_reply_submit(self, text: str) -> None:
        """Send query to daemon when user submits from inline stream reply."""
        self._send_reply(text)

    def _send_reply(self, text: str) -> None:
        """Common handler for reply submissions."""
        if not text.strip():
            return
        msg = {
            "action": "query",
            "text": text.strip(),
            "conversation_id": self._conv_id,
        }
        self._convo_reply.clear()
        self._stream_reply.clear()
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
            "conversation_id": conv_id,
        }
        threading.Thread(
            target=self._send_to_daemon, args=(msg,), daemon=True
        ).start()

    def _send_to_daemon(self, msg: dict) -> None:
        """Send JSON message to the daemon socket."""
        sock_path = resolve_socket_path()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(str(sock_path))
                s.sendall((json.dumps(msg) + "\n").encode())
        except OSError:
            log.exception("Failed to send to daemon at %s", sock_path)

    def _on_key(self, ctl, keyval, keycode, state) -> bool:
        """Window-level keyboard handler."""
        self._cancel_dismiss_timer()
        if keyval == Gdk.KEY_Escape:
            self.handle_clear()
            return True

        shift = state & Gdk.ModifierType.SHIFT_MASK

        if self._state == OverlayState.DISPLAY:
            if keyval == Gdk.KEY_Tab and not shift:
                self._action_bar.child_focus(Gtk.DirectionType.TAB_FORWARD)
                return True
            if keyval == Gdk.KEY_Tab and shift:
                if self._conv_id:
                    self._load_convo(self._conv_id)
                return True
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                focused = self.get_focus()
                if isinstance(focused, Gtk.Button):
                    focused.activate()
                else:
                    self._on_reply_clicked(None)
                return True

        if self._state == OverlayState.CONVO:
            if keyval == Gdk.KEY_Tab and shift:
                if self._conv_id:
                    self._load_convo(self._conv_id)
                return True

        return False
