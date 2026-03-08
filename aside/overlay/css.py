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
    Missing keys fall back to defaults.
    """
    bg = rgb_strip_alpha(colors.get("background", "#0f0f14"))
    fg = rgb_strip_alpha(colors.get("foreground", "#e2e8f0"))
    border = rgb_strip_alpha(colors.get("border", "#2a2a3a"))
    accent = rgb_strip_alpha(colors.get("accent", "#8b5cf6"))
    user_accent = rgb_strip_alpha(colors.get("user_accent", "#22d3ee"))
    bg_opacity = max(0.0, min(1.0, opacity))

    font_rule = f'font-family: "{font}";' if font else ""

    return f"""
window {{
    background-color: transparent;
}}
window.background {{
    background-color: transparent;
}}
.overlay-container {{
    background-color: alpha({bg}, {bg_opacity});
    border-radius: 12px;
    border: 1px solid alpha({border}, 0.5);
    padding: 0;
    {font_rule}
}}
textview {{
    background: transparent;
}}
textview text {{
    background: transparent;
    color: {fg};
}}
.accent-bar {{
    min-height: 3px;
}}
.message-view {{
    background: transparent;
    padding: 6px 0;
}}
.message-user {{
    border-left: 3px solid alpha({user_accent}, 0.6);
    margin-left: 8px;
}}
.message-llm {{
    border-left: 3px solid alpha({accent}, 0.4);
    margin-left: 8px;
}}
.message-user textview text {{
    color: {user_accent};
}}
.message-llm textview text {{
    color: {fg};
}}
.reply-input {{
    background-color: alpha({user_accent}, 0.04);
    border-radius: 8px;
    border: 1px solid alpha({user_accent}, 0.3);
    margin: 8px 12px;
    padding: 0;
    caret-color: {user_accent};
}}
.reply-input:focus-within {{
    border-color: alpha({user_accent}, 0.6);
}}
.reply-input textview {{
    background: transparent;
}}
.reply-input textview text {{
    background: transparent;
    color: {fg};
}}
.picker {{
    background: transparent;
}}
.picker-title {{
    font-size: 1.1em;
    font-weight: bold;
    color: {accent};
    margin: 12px 16px 4px 16px;
}}
.picker-listbox {{
    background: transparent;
}}
.picker-row {{
    border-radius: 6px;
    margin: 2px 8px;
    padding: 8px 12px;
    color: {fg};
}}
.picker-row:selected {{
    background-color: alpha({accent}, 0.15);
}}
.picker-input {{
    background-color: alpha({user_accent}, 0.04);
    border-radius: 8px;
    border: 1px solid alpha({user_accent}, 0.3);
    margin: 4px 12px;
}}
.picker-input:focus-within {{
    border-color: alpha({user_accent}, 0.6);
}}
.picker-input textview {{
    background: transparent;
}}
.picker-input textview text {{
    background: transparent;
    color: {fg};
}}
.input-hint {{
    font-size: 0.8em;
    color: alpha({fg}, 0.35);
    margin: 2px 16px 8px 16px;
}}
.action-bar {{
    padding: 4px 16px 8px 16px;
}}
.action-bar button {{
    background: alpha({accent}, 0.1);
    border: 1px solid alpha({accent}, 0.3);
    border-radius: 6px;
    color: alpha({fg}, 0.85);
    padding: 4px 12px;
    font-size: 0.85em;
}}
.action-bar button:hover {{
    background: alpha({accent}, 0.2);
    color: {fg};
    border-color: alpha({accent}, 0.5);
}}
.dim-label {{
    color: alpha({fg}, 0.4);
    font-size: 0.85em;
}}
"""
