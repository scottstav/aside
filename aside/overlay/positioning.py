"""Pure position/size logic for the overlay — no GTK imports.

Single interpreter of position strings and single source of the
slot/direction vocabulary. cli.py and window.py both import from here;
neither parses position strings itself.
"""

from __future__ import annotations

_ROWS = ("top", "bottom")
_COLS = ("left", "center", "right")

SLOTS = tuple(f"{row}-{col}" for row in _ROWS for col in _COLS)
DIRECTIONS = ("up", "down", "left", "right")

MIN_WIDTH = 250
MIN_MAX_HEIGHT = 150
MAX_DIMENSION = 4000


def normalize_position(position: str) -> tuple[str, str]:
    """Map any position string to a (row, col) grid cell.

    Mirrors the substring semantics the window has always applied to the
    config value: "bottom" substring -> bottom row, else top; "left"
    substring -> left column, elif "right" -> right, else center.
    """
    row = "bottom" if "bottom" in position else "top"
    if "left" in position:
        col = "left"
    elif "right" in position:
        col = "right"
    else:
        col = "center"
    return row, col


def step_position(current: str, direction: str) -> str:
    """Step one slot in `direction` from `current`, clamping at edges."""
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction: {direction!r}")
    row, col = normalize_position(current)
    if direction == "up":
        row = "top"
    elif direction == "down":
        row = "bottom"
    elif direction == "left":
        col = _COLS[max(0, _COLS.index(col) - 1)]
    else:  # right
        col = _COLS[min(len(_COLS) - 1, _COLS.index(col) + 1)]
    return f"{row}-{col}"


def anchor_spec(position: str) -> dict[str, str]:
    """Declarative anchoring for a position: {edge_name: config_margin_key}.

    Edges not in the dict are unanchored. The bottom edge deliberately
    reuses the "margin_top" config value — existing config-compat quirk.
    """
    row, col = normalize_position(position)
    spec = {row: "margin_top"}
    if col == "left":
        spec["left"] = "margin_left"
    elif col == "right":
        spec["right"] = "margin_right"
    return spec


def parse_size_spec(spec: str | int, current: int) -> int:
    """Parse a size spec: "+50"/"-50" relative to current, "450" absolute.

    A plain int is absolute. Raises ValueError on anything else.
    """
    if isinstance(spec, bool):
        raise ValueError(f"invalid size spec: {spec!r}")
    if isinstance(spec, int):
        return spec
    if not isinstance(spec, str):
        raise ValueError(f"invalid size spec: {spec!r}")
    s = spec.strip()
    if not s:
        raise ValueError("empty size spec")
    if s[0] in "+-":
        return current + int(s)  # int("+50") == 50, int("-50") == -50
    return int(s)


def clamp_size(value: int, minimum: int, maximum: int) -> int:
    """Clamp value into [minimum, maximum]."""
    return max(minimum, min(maximum, value))
