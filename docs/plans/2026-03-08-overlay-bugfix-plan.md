# Overlay Bugfix & Polish Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix visual styling, functional bugs, and interaction model in the GTK4 overlay so it's actually usable.

**Architecture:** Fix CSS and widget styling first (everything looks wrong on broken styling), then fix functional bugs (state machine simplification, auto-dismiss, mouse clicks, keyboard nav, reply clearing), then clean up CLI.

**Tech Stack:** Python, GTK4/PyGObject, Cairo, CSS

**Test command:** `source .venv/bin/activate && python -m pytest tests/ -x -q -k "not test_get_key_found"`

**Deploy to VM:** `dev/vm-sync.sh --python-only`

---

### Task 1: Fix CSS — transparent TextViews and clean spacing

The MessageView and ReplyInput TextViews render with opaque white/black backgrounds that clash with the dark overlay. Every TextView must be transparent. The message padding is doubled (CSS class + widget margins). Fix it.

**Files:**
- Modify: `aside/overlay/css.py`
- Modify: `aside/overlay/message_view.py`
- Test: `tests/test_overlay_css.py`

**Step 1: Update CSS in `aside/overlay/css.py`**

Replace the `build_css` function body. Key changes:
- Add `textview` and `textview text` rules: `background: transparent; color: {fg};`
- Remove padding from `.message-view` — the TextView handles it via margins
- Make `.message-user` a lighter accent instead of bold (role label, not whole message)
- Fix `.reply-input` — add `textview` and `textview text` transparency rules inside it
- Add `.picker-input` styling (transparent textview)
- Remove box-shadow from `.reply-input:focus` (GTK4 doesn't support it well)

The full CSS should be:

```python
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
```

**Step 2: Fix MessageView margins in `aside/overlay/message_view.py`**

Remove the hard-coded margins from the TextView widget. Set sensible defaults:

```python
self._textview.set_top_margin(4)
self._textview.set_bottom_margin(4)
self._textview.set_left_margin(16)
self._textview.set_right_margin(16)
```

**Step 3: Update CSS test in `tests/test_overlay_css.py`**

Update the test that checks for CSS classes. The class list should now include: `textview`, `textview text`, `.overlay-container`, `.accent-bar`, `.message-view`, `.message-user`, `.message-llm`, `.reply-input`, `.reply-input:focus-within`, `.picker`, `.picker-title`, `.picker-listbox`, `.picker-row`, `.picker-row:selected`, `.picker-input`, `.input-hint`, `.action-bar`, `.dim-label`.

Update `test_contains_overlay_classes` to check for these new classes and remove checks for old ones (`.reply-input:focus`, `.action-bar` rules may differ).

**Step 4: Run tests, verify pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_css.py -x -q`

**Step 5: Deploy to VM and visually verify**

Run: `dev/vm-sync.sh --python-only`

Then test: `dev/vm-sync.sh --query "what is 2+2"`

**Step 6: Commit**

```
git add aside/overlay/css.py aside/overlay/message_view.py tests/test_overlay_css.py
git commit -m "fix(overlay): transparent TextViews, clean CSS spacing"
```

---

### Task 2: Fix accent bar — clip to container border radius

The accent bar draws a flat rectangle that visually breaks the rounded overlay corners. Fix the Cairo draw function to clip to rounded top corners matching the container's border-radius.

**Files:**
- Modify: `aside/overlay/accent_bar.py`

**Step 1: Update `_draw` method in `aside/overlay/accent_bar.py`**

At the start of `_draw`, before any state-specific drawing, add a clipping path with rounded top corners. Use the container's border-radius (12px from CSS). Add a `corner_radius` parameter to `__init__`.

Add a helper to draw a rounded-top rectangle path:

```python
def _rounded_top_clip(cr, width, height, radius):
    """Set a clip path with rounded top corners, flat bottom."""
    cr.new_path()
    cr.move_to(0, height)
    cr.line_to(0, radius)
    cr.arc(radius, radius, radius, math.pi, 1.5 * math.pi)
    cr.line_to(width - radius, 0)
    cr.arc(width - radius, radius, radius, 1.5 * math.pi, 2 * math.pi)
    cr.line_to(width, height)
    cr.close_path()
    cr.clip()
```

Call this at the top of `_draw` before any fill operations.

Update `__init__` to accept `corner_radius: int = 12` and store it as `self._corner_radius`.

Update all the `_draw` state branches — they don't need to change, the clip handles it.

**Step 2: Update window.py to pass corner_radius**

In `aside/overlay/window.py`, when creating the AccentBar, pass `corner_radius=12` (or read from config).

**Step 3: Update test**

In `tests/test_overlay_accent_bar.py`, update the AccentBar instantiation to include `corner_radius` if needed, or verify the default works.

**Step 4: Run tests, verify pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_accent_bar.py -x -q`

**Step 5: Deploy and verify visually**

Run: `dev/vm-sync.sh --python-only`

**Step 6: Commit**

```
git commit -m "fix(overlay): clip accent bar to container border radius"
```

---

### Task 3: Simplify state machine — remove REPLY state, merge into CONVO

Remove the REPLY overlay state. The stream view's "Reply" button now loads the full conversation (CONVO state). `aside reply <id>` (bare) becomes an alias for `aside view <id>`.

**Files:**
- Modify: `aside/overlay/window.py`
- Modify: `aside/cli.py`
- Modify: `tests/test_overlay_window.py`
- Modify: `tests/test_cli.py`

**Step 1: Update `aside/overlay/window.py`**

1. Remove `REPLY = "reply"` from `OverlayState` enum
2. Remove `self._stream_reply` widget entirely (the ReplyInput that was appended to stream_box)
3. Change `_on_reply_clicked` to call `self._load_convo(self._conv_id)` if conv_id exists, else do nothing
4. Remove `handle_reply` method — `handle_convo` handles everything
5. In `_set_state`, remove `OverlayState.REPLY` from the keyboard mode check
6. Remove the Shift+Tab handler from `_on_key` (no REPLY state to expand from)

**Step 2: Update `aside/cli.py`**

In `_cmd_reply`, when called with bare `aside reply <id>` (no text), send `{"cmd":"convo","conversation_id":...}` instead of `{"cmd":"reply",...}`. This makes it identical to `aside view`.

**Step 3: Update `aside/overlay/app.py` dispatch**

In `_dispatch`, map the `"reply"` command to `handle_convo` (for backward compat if anyone sends it). Or just remove the separate handling — `handle_convo` does the same thing now.

**Step 4: Update tests**

In `tests/test_overlay_window.py`, remove any test for REPLY state. Update state enum test to check 5 states.

In `tests/test_cli.py`, update `test_reply_bare_sends_to_overlay` to expect `{"cmd":"convo",...}`.

**Step 5: Run tests, verify pass**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q -k "not test_get_key_found"`

**Step 6: Commit**

```
git commit -m "refactor(overlay): remove REPLY state, merge into CONVO"
```

---

### Task 4: Auto-dismiss timer + mouse click interactions

After `handle_done()`, start a configurable auto-dismiss timer. Mouse clicks: left=dismiss, middle=stop TTS, right=cancel query.

**Files:**
- Modify: `aside/overlay/window.py`
- Test: `tests/test_overlay_window.py`

**Step 1: Add auto-dismiss timer to `aside/overlay/window.py`**

Add `self._dismiss_timer_id: int | None = None` to `__init__`.

Add methods:

```python
def _start_dismiss_timer(self, seconds: float = 5.0) -> None:
    self._cancel_dismiss_timer()
    self._dismiss_timer_id = GLib.timeout_add(
        int(seconds * 1000), self._on_dismiss_timeout
    )

def _cancel_dismiss_timer(self) -> None:
    if self._dismiss_timer_id is not None:
        GLib.source_remove(self._dismiss_timer_id)
        self._dismiss_timer_id = None

def _on_dismiss_timeout(self) -> bool:
    self._dismiss_timer_id = None
    if self._state == OverlayState.DISPLAY:
        self.handle_clear()
    return False  # don't repeat
```

In `handle_done()`, call `self._start_dismiss_timer()`.

In `handle_clear()`, call `self._cancel_dismiss_timer()`.

Cancel the timer whenever the user interacts: in `_on_key`, `_on_reply_clicked`, and when entering CONVO/PICKER states.

**Step 2: Add mouse click handling**

Add a `Gtk.GestureClick` controller to the window in `__init__`:

```python
# Mouse click controller
click = Gtk.GestureClick()
click.set_button(0)  # all buttons
click.connect("pressed", self._on_click)
self.add_controller(click)
```

Add handler:

```python
def _on_click(self, gesture, n_press, x, y) -> None:
    button = gesture.get_current_button()
    if button == 1:  # left click
        if self._state == OverlayState.DISPLAY:
            self.handle_clear()
    elif button == 2:  # middle click — stop TTS
        msg = {"action": "stop_tts"}
        threading.Thread(target=self._send_to_daemon, args=(msg,), daemon=True).start()
    elif button == 3:  # right click — cancel query + TTS
        msg = {"action": "cancel"}
        threading.Thread(target=self._send_to_daemon, args=(msg,), daemon=True).start()
        self.handle_clear()
```

**Step 3: Simplify action bar**

In the stream view setup, change the action bar to only have a "Reply" button (remove "Dismiss" since left-click handles it):

```python
reply_btn = Gtk.Button(label="Reply")
reply_btn.connect("clicked", self._on_reply_clicked)
self._action_bar.append(reply_btn)
```

**Step 4: Run tests, verify pass**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q -k "not test_get_key_found"`

**Step 5: Deploy and test**

Run: `dev/vm-sync.sh --python-only`

Test: send a query, wait 5 seconds, overlay should auto-dismiss. Left-click should dismiss immediately. Right-click should cancel.

**Step 6: Commit**

```
git commit -m "feat(overlay): auto-dismiss timer, mouse click interactions"
```

---

### Task 5: Fix reply box — clear on transition, clear after submit

The reply input shows stale text from the previous response. Ensure it's cleared on every transition to CONVO and after submitting.

**Files:**
- Modify: `aside/overlay/window.py`

**Step 1: Fix `_load_convo` and `_on_submit`**

In `_load_convo`, the `self._convo_reply.clear()` call is already there. The bug is likely that `_on_submit` doesn't clear after sending. Fix:

```python
def _on_submit(self, text: str) -> None:
    if not text.strip():
        return
    msg = {
        "action": "query",
        "text": text.strip(),
        "conversation_id": self._conv_id,
    }
    self._convo_reply.clear()
    threading.Thread(target=self._send_to_daemon, args=(msg,), daemon=True).start()
```

Also verify `_on_picker_submit` clears the picker text:

```python
def _on_picker_submit(self, text: str, conv_id: str) -> None:
    if not text.strip():
        return
    msg = {
        "action": "query",
        "text": text.strip(),
        "conversation_id": conv_id if conv_id != "__new__" else "__new__",
    }
    threading.Thread(target=self._send_to_daemon, args=(msg,), daemon=True).start()
    # Transition to streaming — the daemon will send open/text/done
    self.handle_clear()
```

**Step 2: Run tests, deploy, verify**

**Step 3: Commit**

```
git commit -m "fix(overlay): clear reply input on transition and after submit"
```

---

### Task 6: Fix picker sizing — dynamic height

The picker is crammed into the overlay's configured width. Give it a larger minimum size so the conversation list is usable.

**Files:**
- Modify: `aside/overlay/window.py`
- Modify: `aside/overlay/picker.py`

**Step 1: Set picker minimum size in `aside/overlay/picker.py`**

In `__init__`, set a minimum height for the list scroll:

```python
list_scroll.set_min_content_height(200)
```

**Step 2: Resize window when showing picker**

In `handle_input()` in `window.py`, temporarily set a larger window size:

```python
def handle_input(self) -> None:
    # ... existing code ...
    self.set_default_size(max(width, 500), 420)
    self.set_visible(True)
    self._picker.focus_input()
```

When leaving picker (in `handle_clear`, `_on_picker_submit`, or transitioning to another state), restore the original size:

Add `self._default_width` in `__init__` to store the configured width. When leaving picker:

```python
self.set_default_size(self._default_width, -1)
```

**Step 3: Run tests, deploy, verify**

**Step 4: Commit**

```
git commit -m "fix(overlay): dynamic picker sizing for usable conversation list"
```

---

### Task 7: Fix picker keyboard navigation

Ctrl+N/P for list navigation and Tab to focus text input don't work. Wire them up.

**Files:**
- Modify: `aside/overlay/picker.py`

**Step 1: Add key controller to picker**

In `ConversationPicker.__init__`, add a key event controller:

```python
key_ctl = Gtk.EventControllerKey()
key_ctl.connect("key-pressed", self._on_key)
self.add_controller(key_ctl)
```

Add the handler:

```python
def _on_key(self, ctl, keyval, keycode, state) -> bool:
    ctrl = state & Gdk.ModifierType.CONTROL_MASK

    if keyval == Gdk.KEY_Tab:
        self._textview.grab_focus()
        return True

    if ctrl and keyval in (Gdk.KEY_n, Gdk.KEY_N):
        self._select_adjacent(1)
        return True

    if ctrl and keyval in (Gdk.KEY_p, Gdk.KEY_P):
        self._select_adjacent(-1)
        return True

    if keyval in (Gdk.KEY_Down,):
        self._select_adjacent(1)
        return True

    if keyval in (Gdk.KEY_Up,):
        self._select_adjacent(-1)
        return True

    return False

def _select_adjacent(self, delta: int) -> None:
    """Select the row delta positions from current selection."""
    current = self._listbox.get_selected_row()
    if current is None:
        idx = 0
    else:
        idx = current.get_index() + delta
    target = self._listbox.get_row_at_index(idx)
    if target is not None:
        self._listbox.select_row(target)
```

**Step 2: Add Gdk import to picker.py**

Ensure `from gi.repository import Gdk, Gtk` is at the top (Gdk is already imported).

**Step 3: Run tests, deploy, verify**

Test: open picker (`aside input`), use Ctrl+N/P to navigate, Tab to focus text input, type and Enter to submit.

**Step 4: Commit**

```
git commit -m "fix(overlay): wire up picker keyboard navigation (Ctrl+N/P, Tab, arrows)"
```

---

### Task 8: Final visual polish pass

Deploy all changes to VM and do a visual review. Fix any remaining CSS issues found during testing.

**Files:**
- Possibly: `aside/overlay/css.py`, `aside/overlay/window.py`, other widget files

**Step 1: Deploy everything**

Run: `dev/vm-sync.sh --python-only`

**Step 2: Test all flows**

1. `dev/vm-sync.sh --query "explain python decorators briefly"` — verify streaming looks clean, auto-dismiss works, left-click dismisses
2. `dev/vm-sync.sh --ssh "~/.local/bin/aside input"` — verify picker opens with proper sizing, keyboard nav works
3. `dev/vm-sync.sh --ssh "~/.local/bin/aside view <recent-id>"` — verify convo view looks clean, reply input is empty

**Step 3: Fix any issues found, commit**

```
git commit -m "fix(overlay): visual polish from manual testing"
```
