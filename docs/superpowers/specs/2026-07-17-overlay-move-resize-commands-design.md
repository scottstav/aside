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
| `{"cmd":"move","position":"top-left"}` | Move to an absolute slot (any of the six). |
| `{"cmd":"move","position":"left"}` | Directional step: `up`, `down`, `left`, `right` move one slot from the current effective position, clamped at grid edges (no wrap). |
| `{"cmd":"move","position":"reset"}` | Clear the override; return to config-defined position. |
| `{"cmd":"resize","width":"+50"}` | Relative width change (`"+N"` / `"-N"`). |
| `{"cmd":"resize","width":"450"}` | Absolute width. |
| `{"cmd":"resize","max_height":"-100"}` | Same forms for `max_height`. Both keys may appear in one command. |
| `{"cmd":"resize","reset":true}` | Clear both size overrides; restore config dimensions. |

Invalid values (unknown position, non-numeric size) are logged and ignored —
consistent with the protocol's existing tolerance for malformed input.

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

- `normalize_position(position: str) -> tuple[str, str]` — maps a position
  string to `(row, col)` using the same substring semantics the window
  applies today (`"bottom" in s` → bottom row else top; `"left"`/`"right"`
  substring → that column, else center). Needed because config accepts loose
  strings (e.g. `"top"`), and directional stepping must start from a
  well-defined grid cell.
- `step_position(current: str, direction: str) -> str` — grid math for
  directional moves. Normalizes `current`, then steps on the 2-row
  (`top`, `bottom`) × 3-column (`left`, `center`, `right`) grid.
  Steps clamp at edges (no wrap). Returns a canonical slot name.
- `parse_size_spec(spec: str, current: int) -> int` — `"+50"`/`"-50"`
  relative to `current`, bare `"450"` absolute. Raises `ValueError` on junk.
- `clamp_size(value: int, minimum: int, maximum: int) -> int` — floors:
  width ≥ 250, max_height ≥ 150; ceiling: monitor-independent generous cap
  (e.g. 4000) since layer-shell clips to output anyway.

No GTK imports — fully unit-testable.

### `aside/overlay/window.py`

- Extract the anchoring block currently inline in `__init__`
  (`window.py:71-89`) into `_apply_position(position: str)`: clear all four
  anchors, then set anchors + margins for the given slot. `__init__` calls it
  with the config position.
- New state: `_position_override: str | None`, `_width_override: int | None`,
  `_max_height_override: int | None` — all in-memory only. Effective values
  resolve as `override if override is not None else config`.
- Internal reads of `self._default_width` / `self._max_height` in sizing code
  (`_on_content_changed`, CONVO sizing in `_set_state`, `handle_clear`) switch
  to effective-value accessors (`_effective_width()`, `_effective_max_height()`).
- `handle_move(spec: str)`: resolve `reset` / absolute slot / directional step
  (via `step_position` against the current effective position), store
  override, call `_apply_position`. Works in any state including HIDDEN
  (takes effect on next show — the layer-shell anchor calls are valid on a
  hidden window).
- `handle_resize(width_spec, max_height_spec, reset)`: parse via
  `parse_size_spec` + `clamp_size`, store overrides, then re-apply:
  `set_size_request(effective_width, ...)`,
  `_history.set_max_content_height(effective_max_height)`, and reset
  `_current_window_h` so `_on_content_changed` recomputes cleanly.

Growth direction stays correct automatically: `_apply_position` sets the
anchor edge, and all growth/sizing logic already keys off the anchored edge.

### `aside/overlay/app.py`

Two new dispatch branches in `_dispatch`: `move` → `handle_move`,
`resize` → `handle_resize`.

### `aside/cli.py`

`move` and `resize` subparsers + `_cmd_move` / `_cmd_resize` handlers
using `_send_overlay`. Position/direction validation happens client-side
(argparse `choices`) *and* overlay-side (defense in depth; the socket is
a public interface).

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
- **Malformed socket input:** logged, ignored, connection continues.

## Out of scope

- Pointer-drag repositioning or edge-drag resizing (rejected; see Problem).
- Persisting moves/resizes to config.
- Cross-monitor placement (layer-shell surface stays on its output).
- Free-form pixel positioning (slots only).

## Testing

- **pytest (no compositor):** `positioning.py` — directional stepping from
  every slot in every direction (24 cases, clamping verified), absolute slot
  passthrough, `parse_size_spec` (relative/absolute/junk), `clamp_size`
  bounds; CLI arg parsing → expected socket payloads (mock `_send_overlay`).
- **VM (manual, `dev/vm-sync.sh`):** all six slots via absolute moves;
  directional stepping walk around the grid; `move reset`; width/max-height
  nudges while a response is streaming; resize in CONVO view; overrides
  survive dismiss + re-open; overrides reset after `systemctl --user restart
  aside-overlay`.
