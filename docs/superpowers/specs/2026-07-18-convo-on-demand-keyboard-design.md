---
type: spec
validated:
  sha: 19ed73bb7247df3a01c529d06b0fbc39f0d6118e
  date: 2026-07-19T01:12:45Z
  reviewers: [fact-check, solid-hygiene]
  findings:
    critical: 0
    important: 0
    medium: 0
    low: 1
    nitpick: 0
  net_negative_remaining: 0
---

# CONVO on-demand keyboard — design

**Date:** 2026-07-18
**Status:** Approved for planning

## Problem

`aside view` (CONVO mode) is built to be a persistent panel — it has no
auto-dismiss timer — but it sets layer-shell keyboard mode EXCLUSIVE, so
while it is open no other application can receive keystrokes. That makes
the core "fly on the wall" workflow impossible: keeping a conversation
open beside another app (e.g. a CAD program), referencing it, copying
from it, and replying to it while working.

Copy/paste is NOT part of this problem: messages render into read-only
`Gtk.TextView`s (`aside/overlay/message_view.py:31-33`), where mouse
selection and Ctrl+C already work whenever the surface can receive input.
The exclusive grab is the only blocker.

## Decision

Change CONVO's keyboard mode from EXCLUSIVE to ON_DEMAND. REPLY and
PICKER keep EXCLUSIVE (they are summon-type-dismiss interactions that
should own the keyboard). All other states keep NONE.

With ON_DEMAND the compositor gives the panel the keyboard only while it
is focused: click the panel to type a reply or select text; click another
window and keystrokes go there while the panel stays visible on the
overlay layer.

**Invariant preserved (the project's core contract):** `aside query`,
`aside query --mic`, and replying inline all continue the conversation
and render the exchange in the visible panel. None of that machinery
involves keyboard state; this change cannot affect it.

## Implementation

The state→mode *decision* goes into the pure module, following the
pattern `positioning.py` established for move/resize: policy is plain
GTK-free Python, `window.py` only applies it.

**`aside/overlay/positioning.py`** — append:

```python
KEYBOARD_MODES = ("exclusive", "on_demand", "none")


def keyboard_mode_for_state(state_value: str) -> str:
    """Keyboard-mode policy per overlay state (state enum's .value string).

    - "reply"/"picker": exclusive — summon-type-dismiss moments own the
      keyboard.
    - "convo": on_demand — persistent panel; keyboard only while focused,
      so other apps stay usable alongside it.
    - everything else: none — never steal focus.
    """
    if state_value in ("reply", "picker"):
        return "exclusive"
    if state_value == "convo":
        return "on_demand"
    return "none"
```

(Takes the enum's `.value` string, not `OverlayState` itself — importing
the enum from `window.py` would drag GTK into the pure module.)

**`OverlayWindow._set_state`** (`aside/overlay/window.py:229-238`) — replace:

```python
        # Keyboard mode: EXCLUSIVE only for states with text input.
        # NONE for display-only states so the overlay never steals focus.
        if new_state in (OverlayState.REPLY, OverlayState.CONVO, OverlayState.PICKER):
            Gtk4LayerShell.set_keyboard_mode(
                self, Gtk4LayerShell.KeyboardMode.EXCLUSIVE
            )
        else:
            Gtk4LayerShell.set_keyboard_mode(
                self, Gtk4LayerShell.KeyboardMode.NONE
            )
```

with:

```python
        # Keyboard mode: policy lives in positioning.keyboard_mode_for_state.
        Gtk4LayerShell.set_keyboard_mode(
            self, _KEYBOARD_MODES[keyboard_mode_for_state(new_state.value)]
        )
```

plus a module-level mapping next to `_LAYER_EDGES`:

```python
_KEYBOARD_MODES = {
    "exclusive": Gtk4LayerShell.KeyboardMode.EXCLUSIVE,
    "on_demand": Gtk4LayerShell.KeyboardMode.ON_DEMAND,
    "none": Gtk4LayerShell.KeyboardMode.NONE,
}
```

and `keyboard_mode_for_state` added to the existing
`from aside.overlay.positioning import ...` in `window.py`.

> **Design note (2026-07-18, spec validation):** Reviewer feedback flagged
> that extending the inline if/else would keep the state→mode policy fused
> with the GTK call — the exact shape `positioning.py` was carved out to
> avoid — leaving it untestable without a compositor. Extracted the policy
> as a pure function (string token in, string token out, same trick as
> `anchor_spec`'s config-key strings), so the mapping is pytest-covered
> for all six states and `_set_state` shrinks to application only.

Documentation: note the panel behavior in `docs/usage.md` (`aside view`
row: panel keeps keyboard only while focused; click back to reply;
Escape dismisses only while focused) and the keyboard-mode table row in
`docs/architecture.md` if one exists.

## Accepted behavior changes

- **Escape dismisses the panel only while it is focused.** Inherent to
  not holding the keyboard, and correct: Escape pressed while another
  app is focused belongs to that app.
- On CONVO entry the compositor may or may not grant initial focus
  (compositor-dependent under ON_DEMAND). Either is acceptable: the
  reply input has GTK-internal focus (`_expand_to_convo` calls
  `focus_input()`), so keystrokes land correctly whenever the surface
  gains the keyboard.

## Out of scope

- Multiple simultaneous conversations/windows (the parked overhaul).
- Any selectability work (already functional).
- REPLY/PICKER keyboard behavior (unchanged by design).
- The pre-existing dead key bindings in DISPLAY state (keyboard mode
  NONE means `_on_key` Tab/Enter handling in DISPLAY cannot fire today;
  unrelated to this change and left as-is).

## Testing

- **pytest:** `keyboard_mode_for_state` — all six state values map to the
  expected token (`hidden/streaming/display → "none"`, `reply/picker →
  "exclusive"`, `convo → "on_demand"`), plus unknown-string fallback to
  `"none"`. The GTK application side (enum mapping + `set_keyboard_mode`
  call) remains compositor-only, verified on the VM. Full suite must stay
  green.
- **VM (manual + `dev/vm-demo.sh` GIF):**
  1. `aside view <id>` → panel opens; `konsole` (or any app) focused →
     typing reaches that app while panel stays visible.
  2. Click the panel → type a reply → response streams into the panel.
  3. Select message text, Ctrl+C, paste into the other app.
  4. `aside query "..."` and a mic-path query while the panel is open
     and unfocused → exchange streams into the panel (invariant check).
  5. Escape with panel focused → dismisses. Escape with other app
     focused → goes to that app; panel stays.
  6. REPLY and PICKER still grab the keyboard as before.
