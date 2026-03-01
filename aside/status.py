"""Waybar status bar module — reads daemon state and outputs JSON.

Designed for waybar's ``custom`` module format:
``{"text": "icon", "tooltip": "details", "class": "idle"}``
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime

from aside.config import load_config, resolve_state_dir


# ---------------------------------------------------------------------------
# Icons (Unicode characters)
# ---------------------------------------------------------------------------

ICON_IDLE = "\uee0d"  #  (claude nerd-font)
ICON_THINKING = "\U000f0674"  # 󰙴 sparkle
ICON_TOOL_USE = "\U000f0493"  # 󰒓 cog
ICON_SPEAKING = "\U000f057e"  # 󰕾 volume_high

_STATUS_ICONS = {
    "idle": ICON_IDLE,
    "thinking": ICON_THINKING,
    "tool_use": ICON_TOOL_USE,
    "speaking": ICON_SPEAKING,
}

# ---------------------------------------------------------------------------
# Model name extraction
# ---------------------------------------------------------------------------

# Maps Claude family names to short display names
_CLAUDE_FAMILIES = {
    "sonnet": "Sonnet",
    "opus": "Opus",
    "haiku": "Haiku",
}


def _extract_model_name(model_id: str) -> str:
    """Extract a human-readable display name from a LiteLLM model identifier.

    Examples::

        anthropic/claude-sonnet-4-6  -> Sonnet 4.6
        anthropic/claude-opus-4-6    -> Opus 4.6
        anthropic/claude-haiku-4-5   -> Haiku 4.5
        openai/gpt-4o               -> gpt-4o
        claude-sonnet-4-6            -> Sonnet 4.6
    """
    if not model_id:
        return ""

    # Strip provider prefix (e.g. "anthropic/")
    if "/" in model_id:
        _, _, model_part = model_id.partition("/")
    else:
        model_part = model_id

    # Try to match Claude model pattern: claude-{family}-{version parts}
    m = re.match(r"claude-(\w+?)-([\d].*)", model_part)
    if m:
        family_key = m.group(1).lower()
        version_raw = m.group(2)  # e.g. "4-6" or "4-6-1"
        family_name = _CLAUDE_FAMILIES.get(family_key)
        if family_name:
            version = version_raw.replace("-", ".")
            return f"{family_name} {version}"

    # Fallback: return the model part without provider
    return model_part


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------


def _build_output(status_data: dict) -> dict:
    """Build waybar JSON output from status.json data.

    Returns a dict with ``text``, ``tooltip``, and ``class`` keys.
    """
    status = status_data.get("status", "idle")
    tool_name = status_data.get("tool_name", "")
    model_id = status_data.get("model", "")
    speak = status_data.get("speak_enabled", False)
    usage = status_data.get("usage", {})

    model_short = _extract_model_name(model_id)
    month_cost = usage.get("month_cost", "$0.00")
    last_cost = usage.get("last_query_cost", "$0.00")

    # Icon
    icon = _STATUS_ICONS.get(status, ICON_IDLE)

    # For active statuses, show the persistent icon + activity indicator
    if status != "idle" and status in _STATUS_ICONS:
        text = f"{ICON_IDLE} {icon}"
        if status == "tool_use" and tool_name:
            text += f" {tool_name}"
    else:
        text = icon

    # Tooltip
    if status == "tool_use" and tool_name:
        tooltip = f"Running: {tool_name}"
    elif status == "thinking":
        tooltip = "Thinking..."
    elif status == "speaking":
        tooltip = "Speaking..."
    else:
        month_name = datetime.now().strftime("%b")
        tooltip = f"{model_short} | {month_name}: {month_cost} | Last: {last_cost}"
        tooltip += " | Voice: ON" if speak else " | Voice: OFF"

    # CSS class
    css_class = status if status in ("idle", "thinking", "speaking", "tool_use") else "idle"

    return {"text": text, "tooltip": tooltip, "class": css_class}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for ``aside status`` subcommand.

    Reads status.json and prints waybar-compatible JSON to stdout.
    """
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    status_file = state_dir / "status.json"

    if not status_file.exists():
        print(json.dumps({
            "text": ICON_IDLE,
            "tooltip": "Aside (not running)",
            "class": "idle",
        }))
        return

    try:
        status_data = json.loads(status_file.read_text())
    except (json.JSONDecodeError, OSError):
        print(json.dumps({
            "text": ICON_IDLE,
            "tooltip": "Aside (error reading status)",
            "class": "idle",
        }))
        return

    output = _build_output(status_data)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
