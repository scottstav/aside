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
from aside.overlay.theme import load_theme_css
from aside.overlay.picker import ConversationPicker
from aside.overlay.reply_input import ReplyInput

log = logging.getLogger(__name__)


class OverlayState(enum.Enum):
    HIDDEN = "hidden"
    STREAMING = "streaming"
    DISPLAY = "display"
    REPLY = "reply"
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
        self._msgs_ready: bool = False  # _on_submit pre-added messages

        overlay_cfg = config.get("overlay", {})
        self._dismiss_timeout: float = overlay_cfg.get("dismiss_timeout", 5.0)
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
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.NONE)
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

        # CSS — load from theme
        theme_name = overlay_cfg.get("theme", "default")
        css_text = load_theme_css(theme_name)
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
        self._accent_bar = AccentBar(corner_radius=12)
        self._main_box.append(self._accent_bar)

        # Header buttons (right-aligned, between accent bar and content)
        header_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        header_btns.set_halign(Gtk.Align.END)
        header_btns.set_margin_end(6)
        header_btns.set_margin_top(2)
        header_btns.set_margin_bottom(0)

        # Check TTS availability
        try:
            from piper import PiperVoice  # noqa: F401
            _tts_available = True
        except ImportError:
            _tts_available = False

        if _tts_available:
            mute_btn = Gtk.Button.new_from_icon_name("audio-volume-muted-symbolic")
            mute_btn.set_tooltip_text("Stop TTS")
            mute_btn.add_css_class("header-btn")
            mute_btn.connect("clicked", self._on_stop_tts_clicked)
            header_btns.append(mute_btn)

        cancel_btn = Gtk.Button.new_from_icon_name("media-playback-stop-symbolic")
        cancel_btn.set_tooltip_text("Cancel query")
        cancel_btn.add_css_class("header-btn")
        cancel_btn.connect("clicked", self._on_cancel_clicked)
        header_btns.append(cancel_btn)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.set_tooltip_text("Dismiss")
        close_btn.add_css_class("header-btn")
        close_btn.connect("clicked", self._on_close_clicked)
        header_btns.append(close_btn)

        self._main_box.append(header_btns)

        # Stack: "main" for content, "picker" for conversation picker
        self._stack = Gtk.Stack()
        self._stack.set_vhomogeneous(False)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)
        self._main_box.append(self._stack)

        # --- Main view (history + action bar + reply) ---
        self._max_height = max_height
        self._current_window_h = 0
        main_view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._history = ConversationHistory(markdown=self._markdown_enabled)
        self._history.set_propagate_natural_height(True)
        self._history.set_max_content_height(max_height)
        main_view.append(self._history)

        # Dynamic window sizing: grow with content, cap at max_height
        vadj = self._history.get_vadjustment()
        if vadj is not None:
            vadj.connect("changed", self._on_content_changed)

        # Action buttons (visible in DISPLAY only)
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

        main_view.append(self._action_bar)

        # Reply input (visible in REPLY and CONVO)
        self._reply = ReplyInput()
        self._reply.connect_submit(self._on_submit)
        self._reply.connect_expand(self._on_expand_convo)
        self._reply.set_visible(False)
        main_view.append(self._reply)

        self._stack.add_named(main_view, "main")

        # --- Picker view ---
        self._picker = ConversationPicker()
        self._picker.connect_submit(self._on_picker_submit)
        self._stack.add_named(self._picker, "picker")

        # Keyboard controller
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctl)

        # Hover pauses auto-dismiss (without stealing focus)
        self._motion = Gtk.EventControllerMotion()
        self._motion.connect("enter", self._on_hover_enter)
        self._motion.connect("leave", self._on_hover_leave)
        self.add_controller(self._motion)

        # Start hidden
        self.set_visible(False)

    @property
    def state(self) -> OverlayState:
        return self._state

    def _set_state(self, new_state: OverlayState) -> None:
        old_state = self._state
        self._state = new_state
        log.debug("state: %s -> %s", old_state.value, new_state.value)

        # Keyboard mode: EXCLUSIVE only for states with text input.
        # NONE for display-only states so the overlay never steals focus.
        if new_state in (OverlayState.REPLY, OverlayState.CONVO, OverlayState.PICKER):
            Gtk4LayerShell.set_keyboard_mode(
                self, Gtk4LayerShell.KeyboardMode.EXCLUSIVE
            )
        else:
            Gtk4LayerShell.set_keyboard_mode(
                self, Gtk4LayerShell.KeyboardMode.NONE
            )

        # Widget visibility (only for main view states)
        if new_state in (
            OverlayState.STREAMING,
            OverlayState.DISPLAY,
            OverlayState.REPLY,
            OverlayState.CONVO,
        ):
            self._action_bar.set_visible(new_state == OverlayState.DISPLAY)
            self._reply.set_visible(
                new_state in (OverlayState.REPLY, OverlayState.CONVO)
            )

        # Window sizing for CONVO: fixed at max_height, history fills remaining space
        if new_state == OverlayState.CONVO:
            self.set_size_request(self._default_width, self._max_height)
            self._current_window_h = self._max_height

    # --- Socket command handlers ---

    def handle_open(self, mode: str = "user", conv_id: str = "") -> None:
        """Show overlay and prepare for streaming."""
        self._stop_thinking_dots()
        self._cancel_dismiss_timer()

        if self._state == OverlayState.CONVO:
            # Streaming into existing convo view — don't switch away.
            if not self._msgs_ready:
                self._history.add_message(mode, "")
            self._msgs_ready = False
            self._accumulated_text = ""
            if conv_id:
                self._conv_id = conv_id
            self._accent_bar.set_state(BarState.STREAMING)
            return

        # All other states: start fresh stream.
        self._conv_id = conv_id or None
        self._accumulated_text = ""
        self._history.clear()
        self._history.add_message(mode, "")
        self._stack.set_visible_child_name("main")
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
            self._history.update_last_message(self._accumulated_text)
        self._accumulated_text = ""
        if self._state != OverlayState.CONVO:
            self._history.add_message("assistant", "")
            self._set_state(OverlayState.STREAMING)
        self._accent_bar.set_state(BarState.STREAMING)

    def handle_text(self, data: str) -> None:
        """Append streamed text to current message."""
        self._stop_thinking_dots()
        self._accumulated_text += data
        self._history.update_last_message(self._accumulated_text)

    def handle_done(self) -> None:
        """Streaming complete."""
        self._accent_bar.set_state(BarState.IDLE)
        if self._state == OverlayState.CONVO:
            # Stay in CONVO. Clear and focus reply for next message.
            self._reply.clear()
            self._reply.focus_input()
            # No dismiss timer in CONVO.
            return
        self._set_state(OverlayState.DISPLAY)
        self._start_dismiss_timer(self._dismiss_timeout)

    def handle_clear(self) -> None:
        """Any->HIDDEN: hide overlay."""
        self._cancel_dismiss_timer()
        self._stop_thinking_dots()
        self._msgs_ready = False
        self.set_visible(False)
        self._current_window_h = 0
        self.set_size_request(self._default_width, -1)
        self._accent_bar.set_state(BarState.IDLE)
        self._set_state(OverlayState.HIDDEN)

    def handle_replace(self, data: str) -> None:
        """Replace all text in current message."""
        self._stop_thinking_dots()
        self._accumulated_text = data
        self._history.update_last_message(data)

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
        self._history.update_last_message(self._thinking_base_text + dots)
        return True

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
        self._expand_to_convo(conv_id)

    def _expand_to_convo(self, conv_id: str) -> None:
        """Load full conversation history and enter CONVO state."""
        self._cancel_dismiss_timer()
        self._msgs_ready = False

        # Enter CONVO state FIRST — this sets min_content_height on the
        # ScrolledWindow so page_size is correct when scroll_to_bottom fires.
        self._stack.set_visible_child_name("main")
        self._set_state(OverlayState.CONVO)
        self.set_visible(True)

        # Now load conversation into the already-visible, correctly-sized widget.
        from aside.state import ConversationStore
        conv_dir = resolve_conversations_dir(self._config)
        store = ConversationStore(conv_dir)
        conv = store.get_or_create(conv_id)
        self._history.load_conversation(conv)

        self._conv_id = conv_id
        self._reply.clear()
        self._accent_bar.set_state(BarState.IDLE)
        self._reply.focus_input()

    # --- Window sizing ---

    def _on_content_changed(self, vadj) -> None:
        """Resize window to fit content, capped at max_height.

        Only active during STREAMING, DISPLAY, and REPLY — CONVO uses fixed
        max_height set by _set_state().
        """
        if self._state not in (
            OverlayState.STREAMING,
            OverlayState.DISPLAY,
            OverlayState.REPLY,
        ):
            return
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
        if self._motion.contains_pointer():
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
        return False

    def _on_hover_enter(self, *_args) -> None:
        """Pause auto-dismiss while cursor is over the overlay."""
        self._cancel_dismiss_timer()

    def _on_hover_leave(self, *_args) -> None:
        """Restart auto-dismiss when cursor leaves — DISPLAY only."""
        if self._state == OverlayState.DISPLAY:
            self._start_dismiss_timer(self._dismiss_timeout)

    # --- User action handlers ---

    def _on_close_clicked(self, button) -> None:
        """Dismiss the overlay."""
        self.handle_clear()

    def _on_cancel_clicked(self, button) -> None:
        """Cancel active query and dismiss."""
        msg = {"action": "cancel"}
        threading.Thread(
            target=self._send_to_daemon, args=(msg,), daemon=True
        ).start()
        self.handle_clear()

    def _on_stop_tts_clicked(self, button) -> None:
        """Stop TTS playback."""
        msg = {"action": "stop_tts"}
        threading.Thread(
            target=self._send_to_daemon, args=(msg,), daemon=True
        ).start()

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
        from aside.config import resolve_archive_dir, resolve_conversations_dir
        from aside.state import ConversationStore
        store = ConversationStore(
            resolve_conversations_dir(self._config),
            archive_dir=resolve_archive_dir(self._config),
        )
        path = store.transcript_path(self._conv_id)
        if path.exists():
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])

    def _on_reply_clicked(self, button) -> None:
        """DISPLAY->REPLY: show reply input."""
        self._cancel_dismiss_timer()
        self._set_state(OverlayState.REPLY)
        self._reply.clear()
        self._reply.focus_input()

    def _on_expand_convo(self) -> None:
        """Shift+Tab: expand to full conversation view."""
        if self._state == OverlayState.CONVO:
            return  # already expanded
        if self._conv_id:
            self._expand_to_convo(self._conv_id)

    def _on_submit(self, text: str) -> None:
        """Send query from REPLY or CONVO state."""
        text = text.strip()
        if not text:
            return
        self._cancel_dismiss_timer()

        if self._state == OverlayState.CONVO:
            # Chat mode: add messages to visible history, stream in-place.
            self._history.add_message("user", text)
            self._history.add_message("assistant", "")
            self._accumulated_text = ""
            self._msgs_ready = True
            self._accent_bar.set_state(BarState.STREAMING)
            self._reply.clear()
        # else: REPLY state — daemon will send open which transitions to STREAMING

        msg = {
            "action": "query",
            "text": text,
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
                    self._expand_to_convo(self._conv_id)
                return True
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                focused = self.get_focus()
                if isinstance(focused, Gtk.Button):
                    focused.activate()
                else:
                    self._on_reply_clicked(None)
                return True

        return False
