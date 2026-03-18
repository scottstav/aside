"""Tests for aside.overlay.accent_bar — animated status bar widget."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.accent_bar import AccentBar, BarState


class TestAccentBar:
    def test_initial_state_is_idle(self):
        bar = AccentBar()
        assert bar.state == BarState.IDLE

    def test_set_state_thinking(self):
        bar = AccentBar()
        bar.set_state(BarState.THINKING)
        assert bar.state == BarState.THINKING

    def test_set_state_listening(self):
        bar = AccentBar()
        bar.set_state(BarState.LISTENING)
        assert bar.state == BarState.LISTENING

    def test_set_state_streaming(self):
        bar = AccentBar()
        bar.set_state(BarState.STREAMING)
        assert bar.state == BarState.STREAMING

    def test_set_state_done(self):
        bar = AccentBar()
        bar.set_state(BarState.DONE)
        assert bar.state == BarState.DONE

    def test_corner_radius_default(self):
        bar = AccentBar()
        assert bar._corner_radius == 12

    def test_corner_radius_custom(self):
        bar = AccentBar(corner_radius=8)
        assert bar._corner_radius == 8
