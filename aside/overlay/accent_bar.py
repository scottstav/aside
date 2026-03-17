"""Animated accent bar widget for the aside overlay."""

from __future__ import annotations

import collections
import enum
import math

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

_WAVEFORM_BARS = 48
_WAVEFORM_HEIGHT = 32


class BarState(enum.Enum):
    """Visual states for the accent bar."""

    IDLE = "idle"
    THINKING = "thinking"
    LISTENING = "listening"
    STREAMING = "streaming"
    DONE = "done"


class AccentBar(Gtk.DrawingArea):
    """Thin animated bar that communicates overlay state via color/motion.

    Reads *accent* and *user_accent* colors from the CSS theme via
    GTK's lookup_color().  Falls back to sensible defaults if not found.

    In LISTENING state, expands to show a live audio waveform fed by
    push_audio_level().
    """

    _DEFAULT_ACCENT = (0.478, 0.635, 0.969)      # #7aa2f7
    _DEFAULT_USER_ACCENT = (0.627, 0.439, 0.282)  # #a07048

    def __init__(
        self,
        corner_radius: int = 12,
    ) -> None:
        super().__init__()
        self.add_css_class("accent-bar")
        self._accent = self._DEFAULT_ACCENT
        self._user_accent = self._DEFAULT_USER_ACCENT
        self._colors_resolved = False
        self._corner_radius = corner_radius
        self._state = BarState.IDLE
        self._progress: float = 0.0
        self._tick_id: int | None = None
        self._last_frame_time: int | None = None
        # Ring buffer of audio levels for waveform (0.0–1.0)
        self._levels: collections.deque[float] = collections.deque(
            [0.0] * _WAVEFORM_BARS, maxlen=_WAVEFORM_BARS
        )
        self.set_size_request(-1, -1)
        self.set_draw_func(self._draw)

    @property
    def state(self) -> BarState:
        return self._state

    def push_audio_level(self, level: float) -> None:
        """Push a new audio level (0.0–1.0) into the waveform buffer."""
        self._levels.append(max(0.0, min(1.0, level)))

    def set_state(self, state: BarState) -> None:
        """Transition to a new bar state, starting/stopping animations."""
        if state == self._state:
            return
        prev = self._state
        self._state = state
        self._progress = 0.0
        self._last_frame_time = None

        if state == BarState.LISTENING:
            self.set_size_request(-1, _WAVEFORM_HEIGHT)
            # Clear waveform buffer
            self._levels.clear()
            self._levels.extend([0.0] * _WAVEFORM_BARS)
        elif prev == BarState.LISTENING:
            self.set_size_request(-1, -1)

        if state in (BarState.THINKING, BarState.LISTENING, BarState.STREAMING, BarState.DONE):
            if self._tick_id is None:
                self._tick_id = self.add_tick_callback(self._on_tick)
        else:
            self._stop_ticking()

        self.queue_draw()

    def _stop_ticking(self) -> None:
        if self._tick_id is not None:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = None
            self._last_frame_time = None

    def _on_tick(self, widget: Gtk.Widget, frame_clock) -> bool:
        frame_time = frame_clock.get_frame_time()

        if self._last_frame_time is not None:
            dt = (frame_time - self._last_frame_time) / 1_000_000.0
        else:
            dt = 0.0
        self._last_frame_time = frame_time

        if self._state == BarState.THINKING:
            self._progress = (self._progress + dt / 2.0) % 1.0
        elif self._state == BarState.LISTENING:
            self._progress = (self._progress + dt / 3.0) % 1.0
        elif self._state == BarState.STREAMING:
            self._progress = (self._progress + dt / 1.5) % 1.0
        elif self._state == BarState.DONE:
            self._progress = min(self._progress + dt / 0.5, 1.0)
            if self._progress >= 1.0:
                self._stop_ticking()
                self.queue_draw()
                return False

        self.queue_draw()
        return True

    @staticmethod
    def _rounded_top_clip(cr, width, height, radius):
        """Set a clip path with rounded top corners, flat bottom."""
        cr.new_path()
        cr.move_to(0, height)
        cr.line_to(0, radius)
        cr.arc(radius, radius, radius, math.pi, 1.5 * math.pi)
        cr.line_to(width - radius, 0)
        cr.arc(width - radius, radius, radius, 1.5 * math.pi, 2 * math.pi)
        cr.line_to(width, height)
        cr.close_path()
        cr.clip()

    def _resolve_colors(self) -> None:
        """Read @define-color accent and user_accent from CSS."""
        ctx = self.get_style_context()
        found, color = ctx.lookup_color("accent")
        if found:
            self._accent = (color.red, color.green, color.blue)
        found, color = ctx.lookup_color("user_accent")
        if found:
            self._user_accent = (color.red, color.green, color.blue)
        self._colors_resolved = True

    def _active_color(self) -> tuple[float, float, float]:
        """Return the color for the current state."""
        if self._state == BarState.LISTENING:
            return self._user_accent
        return self._accent

    def _draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if not self._colors_resolved:
            self._resolve_colors()
        if self._corner_radius > 0:
            self._rounded_top_clip(cr, width, height, self._corner_radius)

        r, g, b = self._active_color()

        if self._state == BarState.IDLE:
            cr.set_source_rgb(r, g, b)
            cr.rectangle(0, 0, width, height)
            cr.fill()

        elif self._state == BarState.THINKING:
            cr.set_source_rgb(r, g, b)
            cr.rectangle(0, 0, width, height)
            cr.fill()

            t = self._progress * 2.0
            if t > 1.0:
                t = 2.0 - t
            cx = t * width
            spot_width = width * 0.15

            import cairo  # type: ignore[import-untyped]

            gradient = cairo.LinearGradient(cx - spot_width, 0, cx + spot_width, 0)
            gradient.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.0)
            gradient.add_color_stop_rgba(0.5, 1.0, 1.0, 1.0, 0.4)
            gradient.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.0)
            cr.set_source(gradient)
            cr.rectangle(0, 0, width, height)
            cr.fill()

        elif self._state == BarState.LISTENING:
            self._draw_waveform(cr, width, height, r, g, b)

        elif self._state == BarState.STREAMING:
            cr.set_source_rgb(r, g, b)
            cr.rectangle(0, 0, width, height)
            cr.fill()

            line_x = self._progress * width
            line_width = max(2, width * 0.02)

            import cairo  # type: ignore[import-untyped]

            gradient = cairo.LinearGradient(line_x - line_width, 0, line_x + line_width, 0)
            gradient.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.0)
            gradient.add_color_stop_rgba(0.5, 1.0, 1.0, 1.0, 0.6)
            gradient.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.0)
            cr.set_source(gradient)
            cr.rectangle(0, 0, width, height)
            cr.fill()

        elif self._state == BarState.DONE:
            alpha = 1.0 - self._progress
            cr.set_source_rgba(r, g, b, alpha)
            cr.rectangle(0, 0, width, height)
            cr.fill()

    def _draw_waveform(self, cr, width, height, r, g, b) -> None:
        """Draw a centered waveform from the audio level buffer."""
        n = len(self._levels)
        if n == 0:
            return

        # Subtle background
        cr.set_source_rgba(r, g, b, 0.08)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        gap = 2
        bar_w = max(2, (width - gap * (n - 1)) / n)
        center_y = height / 2.0
        min_h = 2  # minimum bar height even at silence

        for i, level in enumerate(self._levels):
            x = i * (bar_w + gap)
            bar_h = max(min_h, level * (height - 4))
            y = center_y - bar_h / 2.0

            # Brighter at higher amplitude
            a = 0.3 + 0.7 * level
            cr.set_source_rgba(r, g, b, a)
            # Rounded rect for each bar
            radius = min(bar_w / 2, bar_h / 2, 2)
            cr.new_path()
            cr.arc(x + radius, y + radius, radius, math.pi, 1.5 * math.pi)
            cr.arc(x + bar_w - radius, y + radius, radius, 1.5 * math.pi, 2 * math.pi)
            cr.arc(x + bar_w - radius, y + bar_h - radius, radius, 0, 0.5 * math.pi)
            cr.arc(x + radius, y + bar_h - radius, radius, 0.5 * math.pi, math.pi)
            cr.close_path()
            cr.fill()
