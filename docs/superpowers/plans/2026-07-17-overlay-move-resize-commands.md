# Overlay Move & Resize Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Runtime repositioning (six anchor slots) and resizing (width/max_height) of the aside overlay via overlay-socket commands and `aside move` / `aside resize` CLI subcommands, as session-only overrides.

**Architecture:** All new logic that can be pure lives in a new GTK-free module `aside/overlay/positioning.py` — the single interpreter of position strings, single source of the slot/direction vocabulary, and home of the `SessionGeometry` override state-holder. `OverlayWindow` gains a thin `_apply_position` (translates declarative anchor specs to layer-shell calls) and two payload handlers; `app.py` gains two dispatch branches; `cli.py` gains two subcommands that emit the wire format.

**Tech Stack:** Python 3, GTK4/PyGObject + gtk4-layer-shell (window layer only), argparse (CLI), pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-overlay-move-resize-commands-design.md` (validated; read it before starting if anything here seems ambiguous).

## Global Constraints

- **Session-only:** overrides live in memory. NOTHING is ever written back to `~/.config/aside/config.toml`. Config is the sole durable source of truth.
- **`positioning.py` must never import `gi`/GTK** — it is pure-Python and fully unit-testable without a compositor.
- **Wire format (exact):** `{"cmd":"move","to":"<slot>"}` | `{"cmd":"move","step":"<direction>"}` | `{"cmd":"move","reset":true}` — exactly one of `to`/`step`/`reset` per command. `{"cmd":"resize","width":"+50"|"-50"|"450","max_height":...}` | `{"cmd":"resize","reset":true}`. Invalid payloads are logged at debug level and ignored (connection unaffected).
- **Vocabulary (exact):** slots = `top-left, top-center, top-right, bottom-left, bottom-center, bottom-right`; directions = `up, down, left, right`. Defined ONCE in `positioning.py`; CLI argparse `choices` and overlay validation import them.
- **Size bounds (exact):** `MIN_WIDTH = 250`, `MIN_MAX_HEIGHT = 150`, `MAX_DIMENSION = 4000`.
- **Preserve the margin quirk:** bottom-anchored positions reuse the `margin_top` config value for the BOTTOM edge margin (existing behavior at `window.py:79`). Do not "fix" this.
- **Directional steps clamp at grid edges — no wrap.**
- **Venv, never system Python.** If `.venv` does not exist in the worktree: `python -m venv .venv --system-site-packages && source .venv/bin/activate && pip install -e .`
- **Test command:** `source .venv/bin/activate && python -m pytest tests/ -x -q` (single file: `python -m pytest tests/test_overlay_positioning.py -x -q`).
- **Every commit message ends with these two trailer lines** (work-account requirement):
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01CirL5c2x8Te4dRk5VEY9Rc
  ```
- **Do NOT run `make dev`** during this plan — that installs onto the live desktop; this branch is verified on the VM (Task 7). The CLAUDE.md "run make dev after every fix" rule applies to fixes on the user's running install, not to feature-branch work in a worktree.

---

### Task 1: Vocabulary constants, `normalize_position`, `step_position`

**Files:**
- Create: `aside/overlay/positioning.py`
- Create: `tests/test_overlay_positioning.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `SLOTS: tuple[str, ...]`, `DIRECTIONS: tuple[str, ...]`, `MIN_WIDTH: int = 250`, `MIN_MAX_HEIGHT: int = 150`, `MAX_DIMENSION: int = 4000`, `normalize_position(position: str) -> tuple[str, str]`, `step_position(current: str, direction: str) -> str` (raises `ValueError` on unknown direction).

- [ ] **Step 0: Bootstrap venv if missing**

Run: `test -d .venv || (python -m venv .venv --system-site-packages && source .venv/bin/activate && pip install -e .)`
Then: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: existing suite passes (GTK-dependent tests may skip; that's fine).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_overlay_positioning.py`:

```python
"""Tests for aside.overlay.positioning — pure position/size logic."""

import pytest

from aside.overlay.positioning import (
    DIRECTIONS,
    MAX_DIMENSION,
    MIN_MAX_HEIGHT,
    MIN_WIDTH,
    SLOTS,
    normalize_position,
    step_position,
)


class TestConstants:
    def test_slots(self):
        assert SLOTS == (
            "top-left", "top-center", "top-right",
            "bottom-left", "bottom-center", "bottom-right",
        )

    def test_directions(self):
        assert DIRECTIONS == ("up", "down", "left", "right")

    def test_size_bounds(self):
        assert MIN_WIDTH == 250
        assert MIN_MAX_HEIGHT == 150
        assert MAX_DIMENSION == 4000


class TestNormalizePosition:
    def test_canonical_slots(self):
        assert normalize_position("top-left") == ("top", "left")
        assert normalize_position("top-center") == ("top", "center")
        assert normalize_position("top-right") == ("top", "right")
        assert normalize_position("bottom-left") == ("bottom", "left")
        assert normalize_position("bottom-center") == ("bottom", "center")
        assert normalize_position("bottom-right") == ("bottom", "right")

    def test_loose_strings_match_window_substring_semantics(self):
        # Same semantics as the anchoring block in OverlayWindow.__init__:
        # "bottom" substring -> bottom row, else top; "left"/"right"
        # substring -> that column, else center.
        assert normalize_position("top") == ("top", "center")
        assert normalize_position("bottom") == ("bottom", "center")
        assert normalize_position("") == ("top", "center")
        assert normalize_position("garbage") == ("top", "center")
        assert normalize_position("bottomleft") == ("bottom", "left")

    def test_left_wins_over_right_like_window_elif(self):
        # window.py checks "left" first, elif "right" — preserve that.
        assert normalize_position("left-right") == ("top", "left")


class TestStepPosition:
    # Exhaustive: 6 slots x 4 directions = 24 cases.
    CASES = {
        ("top-left", "up"): "top-left",          # clamp
        ("top-left", "down"): "bottom-left",
        ("top-left", "left"): "top-left",         # clamp
        ("top-left", "right"): "top-center",
        ("top-center", "up"): "top-center",       # clamp
        ("top-center", "down"): "bottom-center",
        ("top-center", "left"): "top-left",
        ("top-center", "right"): "top-right",
        ("top-right", "up"): "top-right",         # clamp
        ("top-right", "down"): "bottom-right",
        ("top-right", "left"): "top-center",
        ("top-right", "right"): "top-right",      # clamp
        ("bottom-left", "up"): "top-left",
        ("bottom-left", "down"): "bottom-left",   # clamp
        ("bottom-left", "left"): "bottom-left",   # clamp
        ("bottom-left", "right"): "bottom-center",
        ("bottom-center", "up"): "top-center",
        ("bottom-center", "down"): "bottom-center",  # clamp
        ("bottom-center", "left"): "bottom-left",
        ("bottom-center", "right"): "bottom-right",
        ("bottom-right", "up"): "top-right",
        ("bottom-right", "down"): "bottom-right",  # clamp
        ("bottom-right", "left"): "bottom-center",
        ("bottom-right", "right"): "bottom-right",  # clamp
    }

    def test_all_24_steps(self):
        for (current, direction), expected in self.CASES.items():
            assert step_position(current, direction) == expected, (
                f"step_position({current!r}, {direction!r})"
            )

    def test_loose_current_is_normalized(self):
        assert step_position("top", "down") == "bottom-center"

    def test_unknown_direction_raises(self):
        with pytest.raises(ValueError):
            step_position("top-center", "diagonal")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_positioning.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'aside.overlay.positioning'`

- [ ] **Step 3: Write the implementation**

Create `aside/overlay/positioning.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_positioning.py -x -q`
Expected: PASS (all tests green)

- [ ] **Step 5: Commit**

```bash
git add aside/overlay/positioning.py tests/test_overlay_positioning.py
git commit -m "feat(overlay): positioning vocabulary, normalize and step functions

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CirL5c2x8Te4dRk5VEY9Rc"
```

---

### Task 2: `anchor_spec`

**Files:**
- Modify: `aside/overlay/positioning.py` (append function)
- Modify: `tests/test_overlay_positioning.py` (append test class)

**Interfaces:**
- Consumes: `normalize_position` (Task 1).
- Produces: `anchor_spec(position: str) -> dict[str, str]` — maps anchored edge name (`"top"`/`"bottom"`/`"left"`/`"right"`) to the config margin key to apply (`"margin_top"`/`"margin_left"`/`"margin_right"`). Edges absent from the dict are unanchored. The vertical edge is ALWAYS present; `center` columns anchor no horizontal edge.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_overlay_positioning.py`:

```python
from aside.overlay.positioning import anchor_spec


class TestAnchorSpec:
    def test_top_center_anchors_top_only(self):
        assert anchor_spec("top-center") == {"top": "margin_top"}

    def test_bottom_center_reuses_margin_top_quirk(self):
        # Existing behavior (window.py bottom branch): the BOTTOM margin
        # is set from the margin_top config value. Preserved deliberately.
        assert anchor_spec("bottom-center") == {"bottom": "margin_top"}

    def test_corners(self):
        assert anchor_spec("top-left") == {"top": "margin_top", "left": "margin_left"}
        assert anchor_spec("top-right") == {"top": "margin_top", "right": "margin_right"}
        assert anchor_spec("bottom-left") == {"bottom": "margin_top", "left": "margin_left"}
        assert anchor_spec("bottom-right") == {"bottom": "margin_top", "right": "margin_right"}

    def test_loose_string(self):
        assert anchor_spec("bottom") == {"bottom": "margin_top"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_positioning.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'anchor_spec'`

- [ ] **Step 3: Write the implementation**

Append to `aside/overlay/positioning.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_positioning.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add aside/overlay/positioning.py tests/test_overlay_positioning.py
git commit -m "feat(overlay): anchor_spec — declarative position-to-anchor mapping

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CirL5c2x8Te4dRk5VEY9Rc"
```

---

### Task 3: `parse_size_spec` and `clamp_size`

**Files:**
- Modify: `aside/overlay/positioning.py` (append functions)
- Modify: `tests/test_overlay_positioning.py` (append test classes)

**Interfaces:**
- Consumes: `MIN_WIDTH`, `MIN_MAX_HEIGHT`, `MAX_DIMENSION` (Task 1).
- Produces: `parse_size_spec(spec: str | int, current: int) -> int` (raises `ValueError` on junk; leading `+`/`-` means relative to `current`, bare number means absolute; a plain `int` is absolute), `clamp_size(value: int, minimum: int, maximum: int) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_overlay_positioning.py`:

```python
from aside.overlay.positioning import clamp_size, parse_size_spec


class TestParseSizeSpec:
    def test_relative_plus(self):
        assert parse_size_spec("+50", 400) == 450

    def test_relative_minus(self):
        assert parse_size_spec("-50", 400) == 350

    def test_absolute_string(self):
        assert parse_size_spec("450", 400) == 450

    def test_absolute_int(self):
        # JSON senders may pass a bare number.
        assert parse_size_spec(450, 400) == 450

    def test_whitespace_tolerated(self):
        assert parse_size_spec(" +50 ", 400) == 450

    def test_junk_raises(self):
        with pytest.raises(ValueError):
            parse_size_spec("wide", 400)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_size_spec("", 400)

    def test_bool_raises(self):
        # True is an int subclass; reject it explicitly.
        with pytest.raises(ValueError):
            parse_size_spec(True, 400)


class TestClampSize:
    def test_below_floor(self):
        assert clamp_size(100, 250, 4000) == 250

    def test_above_ceiling(self):
        assert clamp_size(9999, 250, 4000) == 4000

    def test_in_range(self):
        assert clamp_size(400, 250, 4000) == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_positioning.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'clamp_size'`

- [ ] **Step 3: Write the implementation**

Append to `aside/overlay/positioning.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_positioning.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add aside/overlay/positioning.py tests/test_overlay_positioning.py
git commit -m "feat(overlay): size spec parsing and clamping

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CirL5c2x8Te4dRk5VEY9Rc"
```

---

### Task 4: `SessionGeometry`

**Files:**
- Modify: `aside/overlay/positioning.py` (append dataclass)
- Modify: `tests/test_overlay_positioning.py` (append test class)

**Interfaces:**
- Consumes: `SLOTS`, `step_position`, `parse_size_spec`, `clamp_size`, `MIN_WIDTH`, `MIN_MAX_HEIGHT`, `MAX_DIMENSION` (Tasks 1, 3).
- Produces: `SessionGeometry` dataclass with constructor `SessionGeometry(config_position: str, config_width: int, config_max_height: int)`; properties `effective_position: str`, `effective_width: int`, `effective_max_height: int`; methods `move_to(slot: str) -> None` (ValueError on unknown slot), `step(direction: str) -> None` (ValueError on unknown direction), `resize(width_spec=None, max_height_spec=None) -> None` (ValueError on junk; atomic — junk in either spec leaves BOTH unchanged), `reset_position() -> None`, `reset_size() -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_overlay_positioning.py`:

```python
from aside.overlay.positioning import SessionGeometry


class TestSessionGeometry:
    def _geo(self):
        return SessionGeometry(
            config_position="top-center", config_width=400, config_max_height=500
        )

    def test_effective_defaults_to_config(self):
        geo = self._geo()
        assert geo.effective_position == "top-center"
        assert geo.effective_width == 400
        assert geo.effective_max_height == 500

    def test_move_to(self):
        geo = self._geo()
        geo.move_to("bottom-right")
        assert geo.effective_position == "bottom-right"

    def test_move_to_unknown_slot_raises(self):
        geo = self._geo()
        with pytest.raises(ValueError):
            geo.move_to("middle-nowhere")
        assert geo.effective_position == "top-center"

    def test_step_from_config_position(self):
        geo = self._geo()
        geo.step("down")
        assert geo.effective_position == "bottom-center"

    def test_step_chains_from_override(self):
        geo = self._geo()
        geo.step("down")
        geo.step("left")
        assert geo.effective_position == "bottom-left"

    def test_step_unknown_direction_raises(self):
        geo = self._geo()
        with pytest.raises(ValueError):
            geo.step("diagonal")

    def test_reset_position(self):
        geo = self._geo()
        geo.move_to("bottom-left")
        geo.reset_position()
        assert geo.effective_position == "top-center"

    def test_resize_relative_and_absolute(self):
        geo = self._geo()
        geo.resize(width_spec="+50")
        assert geo.effective_width == 450
        geo.resize(max_height_spec="300")
        assert geo.effective_max_height == 300
        assert geo.effective_width == 450  # untouched

    def test_resize_clamps(self):
        geo = self._geo()
        geo.resize(width_spec="10", max_height_spec="99999")
        assert geo.effective_width == 250     # MIN_WIDTH
        assert geo.effective_max_height == 4000  # MAX_DIMENSION

    def test_resize_relative_chains_from_override(self):
        geo = self._geo()
        geo.resize(width_spec="+50")
        geo.resize(width_spec="+50")
        assert geo.effective_width == 500

    def test_resize_atomic_on_junk(self):
        geo = self._geo()
        with pytest.raises(ValueError):
            geo.resize(width_spec="+50", max_height_spec="junk")
        assert geo.effective_width == 400       # width NOT applied
        assert geo.effective_max_height == 500

    def test_reset_size(self):
        geo = self._geo()
        geo.resize(width_spec="+100", max_height_spec="-100")
        geo.reset_size()
        assert geo.effective_width == 400
        assert geo.effective_max_height == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_positioning.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'SessionGeometry'`

- [ ] **Step 3: Write the implementation**

Append to `aside/overlay/positioning.py` (add `from dataclasses import dataclass, field` to the imports at the top of the file):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_positioning.py -x -q`
Expected: PASS

- [ ] **Step 5: Run the full suite (guard against import breakage)**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: PASS (GTK-dependent tests may skip)

- [ ] **Step 6: Commit**

```bash
git add aside/overlay/positioning.py tests/test_overlay_positioning.py
git commit -m "feat(overlay): SessionGeometry — session-only geometry overrides

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CirL5c2x8Te4dRk5VEY9Rc"
```

---

### Task 5: Window integration — `_apply_position`, `handle_move`, `handle_resize` + app dispatch

**Files:**
- Modify: `aside/overlay/window.py` (imports; `__init__` lines ~53-89; `_set_state` CONVO sizing ~255-258; `_on_content_changed` ~429-447; `handle_clear` ~330-332; new methods `_apply_position`, `handle_move`, `handle_resize`)
- Modify: `aside/overlay/app.py` (`_dispatch`, after the `"input"` branch at line ~137)

**Interfaces:**
- Consumes: `SessionGeometry`, `anchor_spec`, `SLOTS`, `DIRECTIONS` from `aside.overlay.positioning` (Tasks 1, 2, 4).
- Produces: `OverlayWindow.handle_move(payload: dict) -> None`, `OverlayWindow.handle_resize(payload: dict) -> None` — both take the full decoded command dict; `OverlayWindow._apply_position(position: str) -> None`. `app.py` dispatches `{"cmd":"move",...}` → `handle_move(cmd)` and `{"cmd":"resize",...}` → `handle_resize(cmd)`.

No new unit tests in this task: `OverlayWindow` cannot be instantiated without a Wayland compositor + layer-shell (existing `tests/test_overlay_window.py` only tests the state enum for this reason). All logic added here is thin delegation to `positioning.py`, which Tasks 1-4 covered. Behavior is verified on the VM in Task 7. The full suite must still pass (imports, no regressions).

- [ ] **Step 1: Update imports in `window.py`**

Add after the existing `from aside.overlay.reply_input import ReplyInput` import:

```python
from aside.overlay.positioning import SessionGeometry, anchor_spec
```

(No `SLOTS`/`DIRECTIONS` here — slot and direction validation is delegated
to `SessionGeometry.move_to`/`.step`, which raise `ValueError`; the window
only catches.)

- [ ] **Step 2: Replace config-frozen dimensions with `SessionGeometry` in `__init__`**

Replace this block (currently `window.py:57-63`):

```python
        # Dimensions
        width = overlay_cfg.get("width", 400)
        self._default_width = width
        max_height = overlay_cfg.get("max_height", 500)
        self.set_title("aside")
        self.set_decorated(False)
        self.set_size_request(width, -1)
```

with:

```python
        # Dimensions & position: config defaults + session-only overrides
        self._overlay_cfg = overlay_cfg
        self._geometry = SessionGeometry(
            config_position=overlay_cfg.get("position", "top-center"),
            config_width=overlay_cfg.get("width", 400),
            config_max_height=overlay_cfg.get("max_height", 500),
        )
        self.set_title("aside")
        self.set_decorated(False)
        self.set_size_request(self._geometry.effective_width, -1)
```

- [ ] **Step 3: Replace the inline anchoring block with `_apply_position`**

Replace this block (currently `window.py:71-89`):

```python
        # Anchoring from config
        position = overlay_cfg.get("position", "top-center")
        margin_top = overlay_cfg.get("margin_top", 10)
        margin_left = overlay_cfg.get("margin_left", 0)
        margin_right = overlay_cfg.get("margin_right", 0)

        if "bottom" in position:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.BOTTOM, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.BOTTOM, margin_top)
        else:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, margin_top)

        if "left" in position:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.LEFT, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.LEFT, margin_left)
        elif "right" in position:
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, True)
            Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.RIGHT, margin_right)
```

with:

```python
        # Anchoring: config position (plus any session override later)
        self._apply_position(self._geometry.effective_position)
```

- [ ] **Step 4: Add `_apply_position`, `handle_move`, `handle_resize` methods**

Add a module-level constant after the `log = logging.getLogger(__name__)` line:

```python
_LAYER_EDGES = {
    "top": Gtk4LayerShell.Edge.TOP,
    "bottom": Gtk4LayerShell.Edge.BOTTOM,
    "left": Gtk4LayerShell.Edge.LEFT,
    "right": Gtk4LayerShell.Edge.RIGHT,
}
```

Add these methods to `OverlayWindow` (place after `handle_convo` / `_expand_to_convo`, before the `# --- Window sizing ---` section):

```python
    # --- Move / resize commands ---

    def _apply_position(self, position: str) -> None:
        """Anchor the surface for `position` — no string parsing here."""
        spec = anchor_spec(position)
        margin_defaults = {"margin_top": 10, "margin_left": 0, "margin_right": 0}
        for name, edge in _LAYER_EDGES.items():
            anchored = name in spec
            Gtk4LayerShell.set_anchor(self, edge, anchored)
            if anchored:
                key = spec[name]
                margin = self._overlay_cfg.get(key, margin_defaults[key])
                Gtk4LayerShell.set_margin(self, edge, margin)
            else:
                Gtk4LayerShell.set_margin(self, edge, 0)

    def handle_move(self, payload: dict) -> None:
        """Move the overlay: exactly one of to/step/reset in the payload."""
        keys = [k for k in ("to", "step", "reset") if k in payload]
        if len(keys) != 1:
            log.debug("move: expected exactly one of to/step/reset, got %r", payload)
            return
        key = keys[0]
        try:
            if key == "to":
                self._geometry.move_to(payload["to"])
            elif key == "step":
                self._geometry.step(payload["step"])
            else:
                self._geometry.reset_position()
        except ValueError:
            log.debug("move: invalid value %r", payload.get(key))
            return
        self._apply_position(self._geometry.effective_position)

    def handle_resize(self, payload: dict) -> None:
        """Resize the overlay: width/max_height specs, or reset:true."""
        if payload.get("reset"):
            self._geometry.reset_size()
        else:
            width_spec = payload.get("width")
            max_height_spec = payload.get("max_height")
            if width_spec is None and max_height_spec is None:
                log.debug("resize: no width/max_height/reset given")
                return
            try:
                self._geometry.resize(width_spec, max_height_spec)
            except ValueError:
                log.debug("resize: invalid specs %r", payload)
                return
        # Re-apply effective sizes.
        self._history.set_max_content_height(self._geometry.effective_max_height)
        self._current_window_h = 0
        if self._state == OverlayState.CONVO:
            self.set_size_request(
                self._geometry.effective_width, self._geometry.effective_max_height
            )
            self._current_window_h = self._geometry.effective_max_height
        else:
            self.set_size_request(self._geometry.effective_width, -1)
            self._on_content_changed(None)
```

- [ ] **Step 5: Switch every remaining `_default_width` / `_max_height` read to the geometry**

All four sites must switch together — a stale width at any one flickers back on the next content change.

In `__init__` (currently `window.py:152-159`), replace:

```python
        # --- Main view (history + action bar + reply) ---
        self._max_height = max_height
        self._current_window_h = 0
        main_view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._history = ConversationHistory(markdown=self._markdown_enabled)
        self._history.set_propagate_natural_height(True)
        self._history.set_max_content_height(max_height)
```

with:

```python
        # --- Main view (history + action bar + reply) ---
        self._current_window_h = 0
        main_view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._history = ConversationHistory(markdown=self._markdown_enabled)
        self._history.set_propagate_natural_height(True)
        self._history.set_max_content_height(self._geometry.effective_max_height)
```

In `_set_state` (currently `window.py:255-258`), replace:

```python
        # Window sizing for CONVO: fixed at max_height, history fills remaining space
        if new_state == OverlayState.CONVO:
            self.set_size_request(self._default_width, self._max_height)
            self._current_window_h = self._max_height
```

with:

```python
        # Window sizing for CONVO: fixed at max_height, history fills remaining space
        if new_state == OverlayState.CONVO:
            self.set_size_request(
                self._geometry.effective_width, self._geometry.effective_max_height
            )
            self._current_window_h = self._geometry.effective_max_height
```

In `handle_clear` (currently `window.py:331-332`), replace:

```python
        self._current_window_h = 0
        self.set_size_request(self._default_width, -1)
```

with:

```python
        self._current_window_h = 0
        self.set_size_request(self._geometry.effective_width, -1)
```

In `_on_content_changed` (currently `window.py:441-447`), replace:

```python
        _, nat_h, _, _ = self._main_box.measure(
            Gtk.Orientation.VERTICAL, self._default_width
        )
        target = min(math.ceil(nat_h), self._max_height)
        if target != self._current_window_h:
            self._current_window_h = target
            self.set_size_request(self._default_width, target)
```

with:

```python
        _, nat_h, _, _ = self._main_box.measure(
            Gtk.Orientation.VERTICAL, self._geometry.effective_width
        )
        target = min(math.ceil(nat_h), self._geometry.effective_max_height)
        if target != self._current_window_h:
            self._current_window_h = target
            self.set_size_request(self._geometry.effective_width, target)
```

Then verify no stragglers: `grep -n "_default_width\|_max_height\b" aside/overlay/window.py`
Expected: only matches inside `self._geometry.effective_max_height` expressions (and none for `_default_width`). Note `max_height = overlay_cfg.get(...)` from the old code must be fully gone.

- [ ] **Step 6: Add dispatch branches in `app.py`**

In `_dispatch` (`aside/overlay/app.py`), after the `elif name == "input":` branch, add:

```python
        elif name == "move":
            self._window.handle_move(cmd)
        elif name == "resize":
            self._window.handle_resize(cmd)
```

- [ ] **Step 7: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: PASS. Also sanity-import: `python -c "import aside.overlay.window"` — expected to fail ONLY with a GTK/display-related error if no display; a `NameError`/`SyntaxError`/`ImportError` about our symbols means the edit is wrong. If GTK isn't importable at all in this environment, `python -c "import ast; ast.parse(open('aside/overlay/window.py').read())"` must succeed.

- [ ] **Step 8: Commit**

```bash
git add aside/overlay/window.py aside/overlay/app.py
git commit -m "feat(overlay): move and resize socket commands

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CirL5c2x8Te4dRk5VEY9Rc"
```

---

### Task 6: CLI subcommands `aside move` / `aside resize`

**Files:**
- Modify: `aside/cli.py` (parser in `_build_parser` after the `view` subparser ~line 213; handlers near `_cmd_view` ~line 290; `_HANDLERS` dict ~line 708; import from positioning at top)
- Modify: `tests/test_cli.py` (parser tests in `TestArgumentParsing`; new handler test class)

**Interfaces:**
- Consumes: `SLOTS`, `DIRECTIONS` from `aside.overlay.positioning` (Task 1); `_send_overlay` (existing, `cli.py:23`); wire format from Task 5 (`handle_move` / `handle_resize` payload shapes).
- Produces: `aside move <slot|direction|reset>` and `aside resize [--width SPEC] [--max-height SPEC] [--reset]` CLI commands; `_cmd_move(args)`, `_cmd_resize(args)`.

Note: `aside/overlay/__init__.py` is empty and `positioning.py` imports no GTK, so importing it from `cli.py` adds no GTK dependency to the CLI path.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, extend the import line (line 14) with the new handlers:

```python
from aside.cli import main, _send, _send_overlay, _send_recv, _build_parser, _cmd_ls, _cmd_show, _cmd_open, _cmd_rm, _cmd_reply, _cmd_input, _cmd_view, _cmd_query, _cmd_set_key, _cmd_get_key, _cmd_models, _cmd_model, _cmd_move, _cmd_resize
```

Add to class `TestArgumentParsing`:

```python
    def test_move_absolute_slot(self):
        args = self.parser.parse_args(["move", "top-left"])
        assert args.command == "move"
        assert args.where == "top-left"

    def test_move_direction(self):
        args = self.parser.parse_args(["move", "up"])
        assert args.where == "up"

    def test_move_reset(self):
        args = self.parser.parse_args(["move", "reset"])
        assert args.where == "reset"

    def test_move_rejects_unknown(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(["move", "diagonal"])

    def test_resize_width(self):
        args = self.parser.parse_args(["resize", "--width", "+50"])
        assert args.command == "resize"
        assert args.width == "+50"
        assert args.max_height is None
        assert args.reset is False

    def test_resize_max_height_and_reset_flag(self):
        args = self.parser.parse_args(["resize", "--max-height", "-100"])
        assert args.max_height == "-100"
        args = self.parser.parse_args(["resize", "--reset"])
        assert args.reset is True
```

Add a new test class (module-level, alongside the existing classes; `argparse` is already imported in the file — if not, add `import argparse`):

```python
class TestMoveResizeHandlers:
    """_cmd_move/_cmd_resize map CLI args onto the wire format."""

    @pytest.fixture(autouse=True)
    def _capture(self, monkeypatch):
        self.sent = []
        monkeypatch.setattr("aside.cli._send_overlay", lambda m: self.sent.append(m))

    def test_move_slot_maps_to_to(self):
        _cmd_move(argparse.Namespace(where="bottom-right"))
        assert self.sent == [{"cmd": "move", "to": "bottom-right"}]

    def test_move_direction_maps_to_step(self):
        _cmd_move(argparse.Namespace(where="left"))
        assert self.sent == [{"cmd": "move", "step": "left"}]

    def test_move_reset_maps_to_reset_true(self):
        _cmd_move(argparse.Namespace(where="reset"))
        assert self.sent == [{"cmd": "move", "reset": True}]

    def test_resize_specs(self):
        _cmd_resize(argparse.Namespace(width="+50", max_height="300", reset=False))
        assert self.sent == [{"cmd": "resize", "width": "+50", "max_height": "300"}]

    def test_resize_width_only(self):
        _cmd_resize(argparse.Namespace(width="450", max_height=None, reset=False))
        assert self.sent == [{"cmd": "resize", "width": "450"}]

    def test_resize_reset(self):
        _cmd_resize(argparse.Namespace(width=None, max_height=None, reset=True))
        assert self.sent == [{"cmd": "resize", "reset": True}]

    def test_resize_no_args_exits_nonzero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _cmd_resize(argparse.Namespace(width=None, max_height=None, reset=False))
        assert exc.value.code == 2
        assert self.sent == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -x -q`
Expected: FAIL — `ImportError: cannot import name '_cmd_move'`

- [ ] **Step 3: Write the implementation**

In `aside/cli.py`, add to the imports (after the `from aside.config import ...` line):

```python
from aside.overlay.positioning import DIRECTIONS, SLOTS
```

In `_build_parser`, after the `view` subparser block (~line 213), add:

```python
    # aside move <slot|direction|reset>
    move_cmd = sub.add_parser("move", help="Move the overlay (session-only)")
    move_cmd.add_argument(
        "where",
        choices=list(SLOTS) + list(DIRECTIONS) + ["reset"],
        help="Absolute slot, directional step, or 'reset' to config position",
    )

    # aside resize [--width SPEC] [--max-height SPEC] [--reset]
    resize_cmd = sub.add_parser("resize", help="Resize the overlay (session-only)")
    resize_cmd.add_argument("--width", help='Width: "+50", "-50", or absolute "450"')
    resize_cmd.add_argument(
        "--max-height", dest="max_height",
        help='Max height: "+100", "-100", or absolute "300"',
    )
    resize_cmd.add_argument(
        "--reset", action="store_true", default=False,
        help="Restore config width/max_height",
    )
```

Near `_cmd_view` (~line 290), add the handlers:

```python
def _cmd_move(args: argparse.Namespace) -> None:
    """Move the overlay to a slot, step a direction, or reset."""
    if args.where in SLOTS:
        _send_overlay({"cmd": "move", "to": args.where})
    elif args.where in DIRECTIONS:
        _send_overlay({"cmd": "move", "step": args.where})
    else:  # "reset" — argparse choices guarantee this is the only other value
        _send_overlay({"cmd": "move", "reset": True})


def _cmd_resize(args: argparse.Namespace) -> None:
    """Resize the overlay width/max_height, or reset to config."""
    if args.reset:
        _send_overlay({"cmd": "resize", "reset": True})
        return
    if args.width is None and args.max_height is None:
        print(
            "Error: resize requires --width, --max-height, or --reset",
            file=sys.stderr,
        )
        sys.exit(2)
    msg: dict = {"cmd": "resize"}
    if args.width is not None:
        msg["width"] = args.width
    if args.max_height is not None:
        msg["max_height"] = args.max_height
    _send_overlay(msg)
```

In `_HANDLERS` (~line 708), add after the `"view"` entry:

```python
    "move": _cmd_move,
    "resize": _cmd_resize,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -x -q`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add aside/cli.py tests/test_cli.py
git commit -m "feat(cli): aside move and aside resize subcommands

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CirL5c2x8Te4dRk5VEY9Rc"
```

---

### Task 7: Docs + VM verification

**Files:**
- Modify: `CLAUDE.md` (Socket Protocol section, after the `{"cmd":"convo",...}` line)
- Modify: `data/config.toml.example` (comment near the `position` lines, ~line 51)

**Interfaces:**
- Consumes: everything from Tasks 1-6 (full feature).
- Produces: documented protocol; VM-verified behavior evidence pasted into the final PR/summary.

- [ ] **Step 1: Document the new socket commands in `CLAUDE.md`**

In the Socket Protocol list, after the `- {"cmd":"convo","conversation_id":"..."} — show conversation history` line, add:

```markdown
- `{"cmd":"move","to":"top-left"}` / `{"cmd":"move","step":"left"}` / `{"cmd":"move","reset":true}` — reposition overlay between the six anchor slots (session-only; exactly one key per command)
- `{"cmd":"resize","width":"+50","max_height":"300"}` / `{"cmd":"resize","reset":true}` — resize overlay; `"+N"`/`"-N"` relative, bare number absolute (session-only)
```

- [ ] **Step 2: Note runtime commands in the config example**

In `data/config.toml.example`, directly above the `# position = "top-center"` line, add:

```toml
# position/width/max_height can be changed at runtime (session-only) with
# `aside move <slot|up|down|left|right|reset>` and `aside resize --width +50`.
```

- [ ] **Step 3: Commit docs**

```bash
git add CLAUDE.md data/config.toml.example
git commit -m "docs: document overlay move/resize commands

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CirL5c2x8Te4dRk5VEY9Rc"
```

- [ ] **Step 4: VM verification**

Follow CLAUDE.md's VM Testing section exactly:

```bash
cd ~/projects/vmt && source .venv/bin/activate
vmt up aside-ubuntu-kde
vmt ssh aside-ubuntu-kde -- "cloud-init status --wait"
cd <this worktree> && dev/vm-sync.sh --setup
```

Then, over `vmt ssh` (or in the SPICE viewer terminal), exercise and record each of:

1. `aside query "hello"` (or `aside reply` to seed content), then `aside move bottom-right` — overlay visibly moves to bottom-right; response growth extends UPWARD (bottom edge pinned).
2. `aside move up` / `aside move left` twice each — walk the grid; clamping at edges (a third `aside move left` is a no-op).
3. `aside move reset` — returns to config position (top-center by default).
4. `aside resize --width +100` while text is displayed — overlay widens, markdown re-wraps.
5. `aside resize --max-height 200`, then stream a long response — growth caps at 200, content scrolls.
6. `aside view` (CONVO mode), then `aside resize --width -100` — fixed-height view narrows immediately.
7. Dismiss the overlay (Escape), `aside query "again"` — the moved/resized geometry PERSISTS (session-only override survives hide/show).
8. `vmt ssh aside-ubuntu-kde -- "systemctl --user restart aside-overlay"`, then `aside query "fresh"` — geometry is BACK at config values (overrides die on restart).
9. `echo '{"cmd":"move","to":"junk"}' | socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/aside-overlay.sock` (on the VM) — overlay unaffected, still responsive.

Record the command outputs / observed behavior for each numbered item. If any item fails, STOP and fix before proceeding — do not paper over.

- [ ] **Step 5: Full suite one more time, then final commit if anything changed**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: PASS

---

## Verification checklist (whole plan)

- [ ] `python -m pytest tests/ -x -q` green.
- [ ] All 9 VM checks in Task 7 recorded with observed results.
- [ ] `grep -rn "config.toml" aside/overlay/positioning.py aside/overlay/window.py | grep -i writ` — nothing writes config.
- [ ] Slot/direction vocabulary greps to exactly one definition site: `grep -rn "top-left" aside/ --include=*.py` hits only `positioning.py` (plus tests).
