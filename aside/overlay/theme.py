"""Theme loading — resolve and read CSS from theme directories."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_BUNDLED_THEMES = Path(__file__).parent / "themes"


def load_theme_css(theme_name: str) -> str:
    """Load CSS from a theme directory.

    Search order:
    1. ~/.config/aside/themes/<name>/style.css  (user themes)
    2. aside/overlay/themes/<name>/style.css     (bundled themes)

    Returns CSS string.  Falls back to bundled "default" if not found.
    """
    # User theme
    user_dir = Path.home() / ".config" / "aside" / "themes" / theme_name
    user_css = user_dir / "style.css"
    if user_css.is_file():
        log.info("Loading user theme: %s", user_css)
        return user_css.read_text()

    # Bundled theme
    bundled_css = _BUNDLED_THEMES / theme_name / "style.css"
    if bundled_css.is_file():
        log.info("Loading bundled theme: %s", bundled_css)
        return bundled_css.read_text()

    # Fallback to bundled default
    if theme_name != "default":
        log.warning("Theme %r not found, falling back to default", theme_name)
        return load_theme_css("default")

    # Should never happen — default theme is always bundled
    raise FileNotFoundError("Bundled default theme not found")
