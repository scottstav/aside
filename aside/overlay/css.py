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
    border-radius: 16px;
    border: 1px solid alpha({border}, 0.4);
    padding: 0;
    {font_rule}
}}
.accent-bar {{
    background-color: {accent};
    border-radius: 16px 16px 0 0;
    min-height: 3px;
}}
.message-view {{
    background: transparent;
    padding: 12px 16px;
    color: {fg};
}}
.message-user {{
    color: {accent};
    font-weight: bold;
    margin-bottom: 4px;
}}
.message-llm {{
    color: {fg};
}}
.reply-input {{
    background-color: alpha({fg}, 0.04);
    border-radius: 8px;
    border: 1px solid alpha({border}, 0.5);
    padding: 8px 12px;
    caret-color: {accent};
    color: {fg};
}}
.reply-input:focus {{
    border-color: {accent};
    box-shadow: 0 0 0 1px alpha({accent}, 0.3);
}}
.picker {{
    background: transparent;
    border-radius: 0;
}}
.picker-row {{
    border-radius: 8px;
    margin: 2px 8px;
    padding: 6px 12px;
    color: {fg};
}}
.picker-row:selected {{
    background-color: alpha({accent}, 0.15);
}}
.input-hint {{
    font-size: 0.8em;
    color: alpha({fg}, 0.35);
    margin-top: 2px;
}}
.action-bar {{
    padding: 4px 12px;
    border-top: 1px solid alpha({border}, 0.3);
}}
"""
