"""Tests for aside.overlay.css — CSS generation from config colors."""

from aside.overlay.css import build_css, rgb_strip_alpha


class TestRgbStripAlpha:
    def test_nine_char_hex_strips_alpha(self):
        assert rgb_strip_alpha("#1a1b26e6") == "#1a1b26"

    def test_seven_char_hex_unchanged(self):
        assert rgb_strip_alpha("#1a1b26") == "#1a1b26"


class TestBuildCss:
    def test_returns_string(self):
        css = build_css({
            "background": "#1a1b26e6",
            "foreground": "#c0caf5ff",
            "border": "#414868ff",
            "accent": "#7aa2f7ff",
        })
        assert isinstance(css, str)
        assert "background-color" in css

    def test_uses_default_colors_when_empty(self):
        css = build_css({})
        assert isinstance(css, str)
        assert "background-color" in css

    def test_contains_overlay_classes(self):
        css = build_css({
            "background": "#1a1b26e6",
            "foreground": "#c0caf5ff",
            "border": "#414868ff",
            "accent": "#7aa2f7ff",
        })
        assert ".message-view" in css
        assert ".reply-input" in css
        assert ".accent-bar" in css
        assert ".picker" in css
