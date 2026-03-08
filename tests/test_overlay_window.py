"""Tests for aside.overlay.window — main window and state machine."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.window import OverlayState


class TestOverlayState:
    """Test the state enum values exist."""
    def test_states_exist(self):
        assert OverlayState.HIDDEN is not None
        assert OverlayState.STREAMING is not None
        assert OverlayState.DISPLAY is not None
        assert OverlayState.CONVO is not None
        assert OverlayState.PICKER is not None

    def test_state_count(self):
        assert len(OverlayState) == 5
