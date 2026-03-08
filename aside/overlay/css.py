"""CSS generation from overlay config colors."""


def rgb_strip_alpha(color: str) -> str:
    """Return '#RRGGBB' from '#RRGGBB' or '#RRGGBBAA'."""
    if len(color) == 9:  # #RRGGBBAA
        return color[:7]
    return color


def build_css(colors: dict, font: str = "") -> str:
    """Generate CSS string for all overlay components.

    *colors* dict may contain: background, foreground, border, accent.
    Missing keys fall back to Tokyo Night defaults.
    """
    bg = rgb_strip_alpha(colors.get("background", "#1a1b26"))
    fg = rgb_strip_alpha(colors.get("foreground", "#c0caf5"))
    border = rgb_strip_alpha(colors.get("border", "#414868"))
    accent = rgb_strip_alpha(colors.get("accent", "#7aa2f7"))

    font_rule = f'font-family: "{font}";' if font else ""

    return f"""
window {{
    background-color: transparent;
}}
window.background {{
    background-color: transparent;
}}
.overlay-container {{
    background-color: alpha({bg}, 0.92);
    border-radius: 12px;
    border: 1px solid alpha({border}, 0.4);
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
}}
.message-user {{
    color: alpha({accent}, 0.85);
}}
.message-llm {{
    color: {fg};
}}
.reply-input {{
    background-color: alpha({fg}, 0.04);
    border-radius: 8px;
    border: 1px solid alpha({border}, 0.5);
    margin: 8px 12px;
    padding: 0;
    caret-color: {accent};
}}
.reply-input:focus-within {{
    border-color: alpha({accent}, 0.6);
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
    margin: 1px 8px;
    padding: 6px 12px;
    color: {fg};
}}
.picker-row:selected {{
    background-color: alpha({accent}, 0.15);
}}
.picker-input {{
    background-color: alpha({fg}, 0.04);
    border-radius: 8px;
    border: 1px solid alpha({border}, 0.5);
}}
.picker-input:focus-within {{
    border-color: alpha({accent}, 0.6);
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
    background: alpha({fg}, 0.06);
    border: 1px solid alpha({border}, 0.3);
    border-radius: 6px;
    color: alpha({fg}, 0.7);
    padding: 4px 12px;
    font-size: 0.85em;
}}
.action-bar button:hover {{
    background: alpha({fg}, 0.1);
    color: {fg};
}}
.dim-label {{
    color: alpha({fg}, 0.4);
    font-size: 0.85em;
}}
"""
