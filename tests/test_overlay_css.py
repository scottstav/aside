"""Tests for aside.overlay.theme — theme CSS loading."""

from pathlib import Path

from aside.overlay.theme import load_theme_css


class TestLoadThemeCss:
    def test_loads_bundled_default(self):
        css = load_theme_css("default")
        assert isinstance(css, str)
        assert "@define-color bg" in css
        assert ".overlay-container" in css

    def test_fallback_to_default_for_missing(self):
        css = load_theme_css("nonexistent-theme-xyz")
        default_css = load_theme_css("default")
        assert css == default_css

    def test_contains_all_overlay_classes(self):
        css = load_theme_css("default")
        for cls in [
            ".overlay-container", ".accent-bar", ".message-view",
            ".message-user", ".message-llm", ".reply-input",
            ".reply-input:focus-within", ".picker", ".picker-title",
            ".picker-listbox", ".picker-row", ".picker-row:selected",
            ".picker-input", ".input-hint", ".action-bar", ".dim-label",
        ]:
            assert cls in css, f"Missing CSS class: {cls}"

    def test_user_theme_takes_priority(self, tmp_path):
        user_theme_dir = tmp_path / ".config" / "aside" / "themes" / "custom"
        user_theme_dir.mkdir(parents=True)
        (user_theme_dir / "style.css").write_text("/* custom */")

        # Monkey-patch home to use tmp_path
        import aside.overlay.theme as theme_mod
        orig = Path.home
        Path.home = staticmethod(lambda: tmp_path)
        try:
            css = theme_mod.load_theme_css("custom")
            assert "/* custom */" in css
        finally:
            Path.home = orig

    def test_bundled_default_has_define_colors(self):
        css = load_theme_css("default")
        for color_name in ["bg", "fg", "border_color", "accent", "user_accent", "code_bg"]:
            assert f"@define-color {color_name}" in css, f"Missing @define-color {color_name}"
