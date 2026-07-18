---
type: spec
validated:
  sha: aea29cf8991f8711511342d44e1722cbae8def7b
  date: 2026-07-17T05:14:17Z
  reviewers: [fact-check, solid-hygiene]
  findings:
    critical: 0
    important: 0
    medium: 2
    low: 3
    nitpick: 0
  net_negative_remaining: 0
---

# Overlay move & resize commands — design

**Date:** 2026-07-17
**Status:** Approved for planning

## Problem

The overlay's position and size are frozen at construction from config
(`position`, `width`, `max_height` in `[overlay]`). Moving or resizing it
requires editing config and restarting the overlay. Users want to reposition
and resize at runtime — e.g. nudge the overlay out of the way of a window
they're reading, or widen it for a long answer — without losing the
predictable "it always opens where I put it" behavior.

An earlier draft explored pointer-drag repositioning. It was rejected:
the overlay is a layer-shell surface (no native compositor dragging), free
placement breaks the anchor-edge-driven growth direction, and a drag grip
adds UI. Commands fit the project's keyboard/CLI-driven ethos and reuse the
existing socket + CLI machinery with zero UI change.

## Decision summary

- Runtime repositioning between the **six existing slots**
  (`top-left`, `top-center`, `top-right`, `bottom-left`, `bottom-center`,
  `bottom-right`) — the vocabulary the config already supports.
- Runtime resizing of **width** and **max_height** by absolute value or
  relative delta.
- Both are **session-only overrides**: they persist across overlay
  show/hide cycles but reset on overlay restart. Config remains the sole
  durable source of truth; nothing is ever written back to config.
- Delivered as **overlay socket commands + CLI subcommands**. No new
  overlay UI (no grip button, no gestures).

## Interface

### Overlay socket commands

Same newline-delimited JSON protocol on `$XDG_RUNTIME_DIR/aside-overlay.sock`:

| Command | Effect |
|---|---|
| `{"cmd":"move","to":"top-left"}` | Move to an absolute slot (any of the six). |
| `{"cmd":"move","step":"left"}` | Directional step: `up`, `down`, `left`, `right` move one slot from the current effective position, clamped at grid edges (no wrap). |
| `{"cmd":"move","reset":true}` | Clear the override; return to config-defined position. |
| `{"cmd":"resize","width":"+50"}` | Relative width change (`"+N"` / `"-N"`). |
| `{"cmd":"resize","width":"450"}` | Absolute width. |
| `{"cmd":"resize","max_height":"-100"}` | Same forms for `max_height`. Both keys may appear in one command. |
| `{"cmd":"resize","reset":true}` | Clear both size overrides; restore config dimensions. |

Exactly one of `to` / `step` / `reset` per `move` command; commands carrying
none or more than one are rejected (logged, ignored).

> **Design note (2026-07-17):** The `move` payload originally multiplexed
> absolute slots, directions, and a `"reset"` sentinel through a single
> `position` field, while `resize` used `reset:true` — two conventions on
> one wire. Reviewer feedback: socket protocols ossify once bound to
> compositor keybinds, and overloading one enum narrows future vocabulary
> (e.g. a `"center"` slot would collide with a direction). Revised to
> per-vocabulary keys (`to` = slot, `step` = direction) and a single reset
> convention (`reset:true` on both commands), so validation is per-vocabulary
> and future slot names cannot collide with direction names. CLI ergonomics
> are unchanged.

Invalid values (unknown position, non-numeric size) are logged and ignored.
This extends the protocol's existing tolerance for malformed input (currently
silently dropped) with a debug log for the new commands.
*(Verified 2026-07-17: was incorrect — the existing protocol drops malformed
input silently; `parse_command` and `_dispatch` have no log calls. Logging is
new behavior, not existing consistency.)*

### CLI subcommands

Thin wrappers over `_send_overlay`, following the `aside input` pattern:

```
aside move top-left|top-center|top-right|bottom-left|bottom-center|bottom-right
aside move up|down|left|right
aside move reset
aside resize --width +50|450 [--max-height -100|300]
aside resize --reset
```

`aside resize` with no arguments prints usage and exits non-zero.
Intended use: bound to compositor keybinds (four directional binds navigate
the whole grid; two binds nudge width).

## Implementation

### `aside/overlay/positioning.py` (new, pure functions)

This module is the **single interpreter** of position strings and the
**single source** of the slot/direction vocabulary. No other module parses
position strings or hardcodes the valid-value sets.

- Constants: `SLOTS` (the six canonical `row-col` names), `DIRECTIONS`
  (`up`, `down`, `left`, `right`), and named size bounds
  (`MIN_WIDTH = 250`, `MIN_MAX_HEIGHT = 150`, `MAX_DIMENSION = 4000`).
  `cli.py` (argparse `choices`) and the overlay-side validation both import
  these — defense in depth without duplicated enums.
- `normalize_position(position: str) -> tuple[str, str]` — maps any position
  string to `(row, col)` using the same substring semantics the window
  applies today (`"bottom" in s` → bottom row else top; `"left"`/`"right"`
  substring → that column, else center). Needed because config accepts loose
  strings (e.g. `"top"`), and directional stepping must start from a
  well-defined grid cell.
- `step_position(current: str, direction: str) -> str` — grid math for
  directional moves. Normalizes `current`, then steps on the 2-row
  (`top`, `bottom`) × 3-column (`left`, `center`, `right`) grid.
  Steps clamp at edges (no wrap). Returns a canonical slot name.
- `anchor_spec(position: str) -> ...` — translates a position string (via
  `normalize_position`) into a declarative description of which edges to
  anchor and which config margins apply. The window's `_apply_position`
  consumes this and only makes the corresponding layer-shell calls — the
  window contains zero position-string parsing.
- `parse_size_spec(spec: str, current: int) -> int` — `"+50"`/`"-50"`
  relative to `current`, bare `"450"` absolute. Raises `ValueError` on junk.
- `clamp_size(value: int, minimum: int, maximum: int) -> int` — clamps to
  the named bounds above.

No GTK imports — fully unit-testable.

> **Design note (2026-07-17):** Reviewer feedback flagged that loose-string
> interpretation would otherwise live in two modules (`normalize_position`
> for stepping, `_apply_position` for anchoring) that could drift silently —
> only one of them unit-testable — and that the slot/direction vocabulary
> appeared in three places (argparse `choices`, overlay validation, grid
> model). Revised so `positioning.py` owns the entire vocabulary and all
> string interpretation; the window translates its declarative output to
> layer-shell calls, and CLI/overlay validation import the same constants.

### `SessionGeometry` (in `aside/overlay/positioning.py`)

A small dataclass owning the session-override lifecycle — the "effective
value = override or config" resolution lives in exactly one place:

- Constructed from config values (`position`, `width`, `max_height`).
- Fields: the three config defaults plus three optional overrides,
  all in-memory only.
- Properties: `effective_position`, `effective_width`,
  `effective_max_height`.
- Methods: `move_to(slot)`, `step(direction)` (delegates to
  `step_position`), `resize(width_spec, max_height_spec)` (delegates to
  `parse_size_spec` + `clamp_size`), `reset_position()`, `reset_size()`.

Pure and unit-testable; the window owns one instance and never resolves
overrides itself.

> **Design note (2026-07-17):** Reviewer feedback flagged that three parallel
> `_x_override` attributes plus scattered `override if not None else config`
> sites would add to `OverlayWindow`'s already-broad attribute soup (~635
> lines, state machine + 12 socket handlers + timers + IPC). Revised to
> group override state and resolution into `SessionGeometry`, giving future
> geometry features (per-edge margins, persistence if ever wanted) one
> obvious home.

### `aside/overlay/window.py`

- Extract the anchoring block currently inline in `__init__`
  (`window.py:71-89`) into `_apply_position(position: str)`: translate the
  position via `positioning.anchor_spec` into anchor/margin settings, clear
  all four anchors, then apply. No string parsing in the window. `__init__`
  calls it with the config position.
- New state: one `SessionGeometry` instance (`self._geometry`), constructed
  from config. Session-only by nature — gone on overlay restart.
- Internal reads of `self._default_width` / `self._max_height` in sizing code
  switch to `self._geometry.effective_width` /
  `self._geometry.effective_max_height`. All three `set_size_request` call
  sites (`_on_content_changed`, CONVO sizing in `_set_state`,
  `handle_clear`) plus the `measure()` width in `_on_content_changed`
  switch together — a stale width at any one of them would flicker back on
  the next content change.
- `handle_move(payload: dict)`: exactly one of `to` / `step` / `reset`;
  validate against `positioning.SLOTS` / `positioning.DIRECTIONS`, update
  `_geometry` accordingly, call
  `_apply_position(self._geometry.effective_position)`. Works in any state
  including HIDDEN (takes effect on next show — the layer-shell anchor
  calls are valid on a hidden window).
- `handle_resize(payload: dict)`: `reset:true` or size specs; delegate
  parsing/clamping to `_geometry.resize` (rejecting junk with a debug log),
  then re-apply: `set_size_request(effective_width, ...)`,
  `_history.set_max_content_height(effective_max_height)`, and reset
  `_current_window_h` so `_on_content_changed` recomputes cleanly.

Growth direction stays correct automatically: `_apply_position` sets the
anchor edge, and all growth/sizing logic already keys off the anchored edge.

### `aside/overlay/app.py`

Two new dispatch branches in `_dispatch`: `move` → `handle_move`,
`resize` → `handle_resize`.

### `aside/cli.py`

`move` and `resize` subparsers + `_cmd_move` / `_cmd_resize` handlers
using `_send_overlay`. `_cmd_move` maps its argument onto the wire format:
a slot name → `{"to": ...}`, a direction → `{"step": ...}`, `reset` →
`{"reset": true}`. Argparse `choices` are imported from
`positioning.SLOTS` / `positioning.DIRECTIONS`; the overlay validates
against the same constants (defense in depth; the socket is a public
interface — but a single-sourced vocabulary).

## Edge cases

- **Move/resize while HIDDEN:** override stored and applied; visible on next
  show. Not an error.
- **Mid-stream move:** safe — streaming growth continues from the new
  anchor edge.
- **CONVO fixed-height mode:** uses effective max_height; a resize while in
  CONVO re-applies the fixed size immediately.
- **Width change with rendered markdown:** GTK re-wraps natively on
  `set_size_request`; no action needed.
- **Margins:** config margins apply to whichever slot is active, with the
  same interpretation as today (including the existing quirk that
  `margin_top` is reused for bottom-anchored positions — preserved as-is).
- **Malformed socket input:** ignored, connection continues (existing
  behavior); the new `move`/`resize` handlers additionally log rejected
  values at debug level.

## Out of scope

- Pointer-drag repositioning or edge-drag resizing (rejected; see Problem).
- Persisting moves/resizes to config.
- Cross-monitor placement (layer-shell surface stays on its output).
- Free-form pixel positioning (slots only).

## Testing

- **pytest (no compositor):** `positioning.py` — directional stepping from
  every slot in every direction (24 cases, clamping verified), absolute slot
  passthrough, `normalize_position` loose-string cases, `anchor_spec`
  output, `parse_size_spec` (relative/absolute/junk), `clamp_size` bounds;
  `SessionGeometry` — override precedence, move/step/resize/reset lifecycle;
  CLI arg parsing → expected socket payloads including the `to`/`step`/
  `reset` mapping (mock `_send_overlay`).
- **VM (manual, `dev/vm-sync.sh`):** all six slots via absolute moves;
  directional stepping walk around the grid; `move reset`; width/max-height
  nudges while a response is streaming; resize in CONVO view; overrides
  survive dismiss + re-open; overrides reset after `systemctl --user restart
  aside-overlay`.
