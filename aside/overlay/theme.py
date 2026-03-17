"""Theme loading — resolve and read CSS from theme directories."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_BUNDLED_THEMES = Path(__file__).parent / "themes"


def _load_bundled_default() -> str:
    """Load the bundled default theme CSS."""
    path = _BUNDLED_THEMES / "default" / "style.css"
    if path.is_file():
        return path.read_text()
    raise FileNotFoundError("Bundled default theme not found")


def load_theme_css(theme_name: str) -> str:
    """Load CSS from a theme directory, layered on top of the default.

    The bundled default theme is always loaded first.  A user theme is
    then appended on top, so partial overrides (e.g. just a font or a
    few @define-color values) work naturally via CSS cascading.

    Search order for the user/named theme:
    1. ~/.config/aside/themes/<name>/style.css  (user themes)
    2. aside/overlay/themes/<name>/style.css     (bundled themes)

    Returns combined CSS string.
    """
    base = _load_bundled_default()

    if theme_name == "default":
        return base

    # User theme
    user_css = Path.home() / ".config" / "aside" / "themes" / theme_name / "style.css"
    if user_css.is_file():
        log.info("Loading user theme: %s", user_css)
        return base + "\n" + user_css.read_text()

    # Bundled theme
    bundled_css = _BUNDLED_THEMES / theme_name / "style.css"
    if bundled_css.is_file():
        log.info("Loading bundled theme: %s", bundled_css)
        return base + "\n" + bundled_css.read_text()

    log.warning("Theme %r not found, using default", theme_name)
    return base
