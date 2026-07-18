"""Pure position/size logic for the overlay — no GTK imports.

Single interpreter of position strings and single source of the
slot/direction vocabulary. cli.py and window.py both import from here;
neither parses position strings itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass
class SessionGeometry:
    """Session-only geometry overrides over config defaults.

    The single home of "effective value = override or config" resolution.
    In-memory only — survives overlay hide/show, gone on restart. Nothing
    here ever writes back to config.
    """

    config_position: str
    config_width: int
    config_max_height: int
    position_override: str | None = field(default=None)
    width_override: int | None = field(default=None)
    max_height_override: int | None = field(default=None)

    @property
    def effective_position(self) -> str:
        return self.position_override or self.config_position

    @property
    def effective_width(self) -> int:
        return self.width_override if self.width_override is not None else self.config_width

    @property
    def effective_max_height(self) -> int:
        return (
            self.max_height_override
            if self.max_height_override is not None
            else self.config_max_height
        )

    def move_to(self, slot: str) -> None:
        if slot not in SLOTS:
            raise ValueError(f"unknown slot: {slot!r}")
        self.position_override = slot

    def step(self, direction: str) -> None:
        self.position_override = step_position(self.effective_position, direction)

    def resize(self, width_spec=None, max_height_spec=None) -> None:
        # Parse both first so junk in either spec applies neither.
        new_width = (
            clamp_size(parse_size_spec(width_spec, self.effective_width), MIN_WIDTH, MAX_DIMENSION)
            if width_spec is not None
            else None
        )
        new_max_height = (
            clamp_size(
                parse_size_spec(max_height_spec, self.effective_max_height),
                MIN_MAX_HEIGHT,
                MAX_DIMENSION,
            )
            if max_height_spec is not None
            else None
        )
        if new_width is not None:
            self.width_override = new_width
        if new_max_height is not None:
            self.max_height_override = new_max_height

    def reset_position(self) -> None:
        self.position_override = None

    def reset_size(self) -> None:
        self.width_override = None
        self.max_height_override = None


def apply_move_payload(geometry: SessionGeometry, payload: dict) -> None:
    """Validate a decoded move payload and apply it to the geometry.

    Exactly one of to/step/reset must be present. Raises ValueError on
    any invalid payload — the caller decides how to report it.
    """
    keys = [k for k in ("to", "step", "reset") if k in payload]
    if len(keys) != 1:
        raise ValueError(f"move: expected exactly one of to/step/reset, got {sorted(payload)}")
    key = keys[0]
    if key == "to":
        geometry.move_to(payload["to"])
    elif key == "step":
        geometry.step(payload["step"])
    elif not payload["reset"]:
        raise ValueError("move: reset must be true")
    else:
        geometry.reset_position()


def apply_resize_payload(geometry: SessionGeometry, payload: dict) -> None:
    """Validate a decoded resize payload and apply it to the geometry.

    Either reset:true, or at least one of width/max_height. Raises
    ValueError on any invalid payload.
    """
    if payload.get("reset"):
        geometry.reset_size()
        return
    width_spec = payload.get("width")
    max_height_spec = payload.get("max_height")
    if width_spec is None and max_height_spec is None:
        raise ValueError("resize: requires width, max_height, or reset")
    geometry.resize(width_spec, max_height_spec)
