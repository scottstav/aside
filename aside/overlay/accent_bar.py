"""Animated accent bar widget for the aside overlay."""

from __future__ import annotations

import enum
import math

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


class BarState(enum.Enum):
    """Visual states for the accent bar."""

    IDLE = "idle"
    THINKING = "thinking"
    LISTENING = "listening"
    STREAMING = "streaming"
    DONE = "done"


def _parse_hex_color(hex_color: str) -> tuple[float, float, float]:
    """Parse #RRGGBB or #RRGGBBAA to (r, g, b) floats in 0-1 range."""
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b)


class AccentBar(Gtk.DrawingArea):
    """Thin animated bar that communicates overlay state via color/motion."""

    def __init__(self, accent_color: str, height: int = 3, corner_radius: int = 12) -> None:
        super().__init__()
        self._color = _parse_hex_color(accent_color)
        self._corner_radius = corner_radius
        self._state = BarState.IDLE
        self._progress: float = 0.0
        self._tick_id: int | None = None
        self._last_frame_time: int | None = None
        self.set_size_request(-1, height)
        self.set_draw_func(self._draw)

    @property
    def state(self) -> BarState:
        return self._state

    def set_state(self, state: BarState) -> None:
        """Transition to a new bar state, starting/stopping animations."""
        if state == self._state:
            return
        self._state = state
        self._progress = 0.0
        self._last_frame_time = None

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
        frame_time = frame_clock.get_frame_time()  # microseconds

        if self._last_frame_time is not None:
            dt = (frame_time - self._last_frame_time) / 1_000_000.0  # seconds
        else:
            dt = 0.0
        self._last_frame_time = frame_time

        if self._state == BarState.THINKING:
            # Sweep cycle: ~2 seconds full cycle
            self._progress = (self._progress + dt / 2.0) % 1.0
        elif self._state == BarState.LISTENING:
            # Breathing cycle: ~3 seconds
            self._progress = (self._progress + dt / 3.0) % 1.0
        elif self._state == BarState.STREAMING:
            # Shimmer: ~1.5 seconds
            self._progress = (self._progress + dt / 1.5) % 1.0
        elif self._state == BarState.DONE:
            # Fade out over ~0.5 seconds
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

    def _draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if self._corner_radius > 0:
            self._rounded_top_clip(cr, width, height, self._corner_radius)

        r, g, b = self._color

        if self._state == BarState.IDLE:
            cr.set_source_rgb(r, g, b)
            cr.rectangle(0, 0, width, height)
            cr.fill()

        elif self._state == BarState.THINKING:
            # Solid bar + bright sweep spot
            cr.set_source_rgb(r, g, b)
            cr.rectangle(0, 0, width, height)
            cr.fill()

            # Ping-pong: progress 0→0.5 goes left-to-right, 0.5→1 right-to-left
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
            # Breathing: opacity oscillates sinusoidally between 0.4 and 1.0
            alpha = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._progress * 2.0 * math.pi))
            cr.set_source_rgba(r, g, b, alpha)
            cr.rectangle(0, 0, width, height)
            cr.fill()

        elif self._state == BarState.STREAMING:
            # Solid bar + thin bright line sweeping across
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
            # Fade out
            alpha = 1.0 - self._progress
            cr.set_source_rgba(r, g, b, alpha)
            cr.rectangle(0, 0, width, height)
            cr.fill()
