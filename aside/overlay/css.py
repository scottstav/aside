"""CSS generation from overlay config colors."""


def rgb_strip_alpha(color: str) -> str:
    """Return '#RRGGBB' from '#RRGGBB' or '#RRGGBBAA'."""
    if len(color) == 9:  # #RRGGBBAA
        return color[:7]
    return color


def build_css(colors: dict, font: str = "", opacity: float = 0.95) -> str:
    """Generate CSS string for all overlay components.

    *colors* dict may contain: background, foreground, border, accent, user_accent.
    *opacity* controls background transparency (0.0–1.0).

    When no colors are configured, uses GTK named theme colors (@theme_bg_color,
    @theme_fg_color, etc.) so the overlay looks native on any theme.
    """
    bg = rgb_strip_alpha(colors["background"]) if "background" in colors else None
    fg = rgb_strip_alpha(colors["foreground"]) if "foreground" in colors else None
    border = rgb_strip_alpha(colors["border"]) if "border" in colors else None
    accent = rgb_strip_alpha(colors["accent"]) if "accent" in colors else None
    user_accent = rgb_strip_alpha(colors["user_accent"]) if "user_accent" in colors else None
    bg_opacity = max(0.0, min(1.0, opacity))

    font_rule = f'font-family: "{font}";' if font else ""

    # Use configured colors or fall back to GTK theme named colors.
    bg_val = f"alpha({bg}, {bg_opacity})" if bg else "@theme_bg_color"
    fg_val = fg or "@theme_fg_color"
    border_val = f"alpha({border}, 0.5)" if border else "alpha(@borders, 0.5)"
    accent_val = accent or "@theme_selected_bg_color"
    user_accent_val = user_accent or "@theme_selected_bg_color"

    # Window must be transparent for layer-shell (rounded corners).
    # The overlay-container restores an opaque background from the theme.
    css = f"""
window {{
    background-color: transparent;
}}
window.background {{
    background-color: transparent;
}}
.overlay-container {{
    background-color: {bg_val};
    border-radius: 12px;
    border: 1px solid {border_val};
    padding: 0;
    {font_rule}
}}
.overlay-container textview {{
    background: transparent;
    color: {fg_val};
}}
.overlay-container textview text {{
    background: transparent;
    color: {fg_val};
}}
.accent-bar {{
    min-height: 4px;
}}
.message-view {{
    padding: 6px 0;
}}
.message-user {{
    margin-left: 8px;
    border-left: 3px solid alpha({user_accent_val}, 0.6);
}}
.message-llm {{
    margin-left: 8px;
    border-left: 3px solid alpha({accent_val}, 0.4);
}}
.message-user textview text {{
    color: {user_accent_val};
}}
.reply-input {{
    border-radius: 8px;
    border: 1px solid alpha({user_accent_val}, 0.3);
    margin: 8px 12px;
    padding: 8px 10px;
    caret-color: {user_accent_val};
    background-color: alpha({user_accent_val}, 0.04);
}}
.reply-input:focus-within {{
    border-color: alpha({user_accent_val}, 0.6);
}}
.reply-input textview {{
    background: transparent;
}}
.reply-input textview text {{
    background: transparent;
    color: {fg_val};
}}
.picker {{
    background: transparent;
}}
.picker-title {{
    font-size: 1.1em;
    font-weight: bold;
    color: {accent_val};
    margin: 12px 16px 4px 16px;
}}
.picker-listbox {{
    background: transparent;
}}
.picker-row {{
    border-radius: 6px;
    margin: 2px 8px;
    padding: 8px 12px;
    color: {fg_val};
}}
.picker-row:selected {{
    background-color: alpha({accent_val}, 0.15);
}}
.picker-input {{
    border-radius: 8px;
    border: 1px solid alpha({user_accent_val}, 0.3);
    margin: 4px 12px;
    background-color: alpha({user_accent_val}, 0.04);
}}
.picker-input:focus-within {{
    border-color: alpha({user_accent_val}, 0.6);
}}
.picker-input textview {{
    background: transparent;
}}
.picker-input textview text {{
    background: transparent;
    color: {fg_val};
}}
.input-hint {{
    font-size: 0.8em;
    color: alpha({fg_val}, 0.35);
    margin: 2px 16px 8px 16px;
}}
.action-bar {{
    padding: 4px 16px 8px 16px;
}}
.action-icon {{
    background: alpha({fg_val}, 0.08);
    border: none;
    border-radius: 50%;
    color: alpha({fg_val}, 0.6);
    min-width: 36px;
    min-height: 36px;
    padding: 6px;
}}
.action-icon:hover {{
    background: alpha({fg_val}, 0.15);
    color: alpha({fg_val}, 0.9);
}}
.dim-label {{
    color: alpha({fg_val}, 0.4);
    font-size: 0.85em;
}}
"""
    return css
