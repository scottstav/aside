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

One change, in `OverlayWindow._set_state` (`aside/overlay/window.py:229-238`).

Replace:

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
        # Keyboard mode per state:
        #   REPLY/PICKER — EXCLUSIVE: summon-type-dismiss moments own the keyboard.
        #   CONVO — ON_DEMAND: persistent panel; keyboard only while focused,
        #     so other apps stay usable alongside it.
        #   Everything else — NONE: never steal focus.
        if new_state in (OverlayState.REPLY, OverlayState.PICKER):
            mode = Gtk4LayerShell.KeyboardMode.EXCLUSIVE
        elif new_state is OverlayState.CONVO:
            mode = Gtk4LayerShell.KeyboardMode.ON_DEMAND
        else:
            mode = Gtk4LayerShell.KeyboardMode.NONE
        Gtk4LayerShell.set_keyboard_mode(self, mode)
```

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

- **pytest:** no new unit tests — the change is a GTK/layer-shell call
  selected by state, not reachable without a compositor. Full suite must
  stay green (426 tests).
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
