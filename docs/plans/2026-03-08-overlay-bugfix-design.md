# Overlay Bugfix & Polish — Design

Date: 2026-03-08

## Problem

First real testing of the GTK4 overlay revealed many issues across visual styling, functional behavior, and missing features.

## Changes

### 1. Simplify state machine: merge REPLY into CONVO

Remove `aside reply` as a separate CLI command and the REPLY overlay state. `aside view <id>` shows conversation history + reply input. The stream view's "Reply" button transitions to CONVO (loads full conversation). This eliminates the duplicated REPLY/CONVO split.

States become: HIDDEN, STREAMING, DISPLAY, CONVO, PICKER (5 states, down from 6).

### 2. Visual fixes (CSS + accent bar)

**Accent bar:** The bar draws a flat rectangle that clashes with the rounded overlay container. Fix: clip the accent bar's Cairo drawing to match the container's top corner radius. The bar should feel like part of the container, not pasted on top.

**MessageView:** The screenshot shows a white-background text area clashing with the dark overlay. The GTK TextView needs `background: transparent` and `color: inherit` so it blends with the container. Remove hard margins from the TextView — padding comes from the `.message-view` CSS class only.

**ReplyInput:** Similar — the text entry needs to blend. Reduce border prominence, match the overlay aesthetic.

**Picker:** Needs its own size management (see section 5).

**General:** Review all CSS classes for conflicting backgrounds, double-padding, and missing transparency.

### 3. Auto-dismiss + mouse click interactions

After `handle_done()`, start a configurable auto-dismiss timer (default: 5 seconds). Any interaction (mouse hover, keyboard) cancels the timer.

Mouse clicks on the overlay window:
- **Left click** on background area: dismiss (handle_clear)
- **Middle click**: stop TTS (`stop_tts` to daemon)
- **Right click**: cancel query + TTS (`cancel` to daemon)

Remove the explicit "Dismiss" and "Reply" buttons from the action bar. Replace with: the stream view just shows the response. Left-click dismisses. To reply, user can use `aside view <id>` or a keyboard shortcut.

Actually — keep a subtle action bar but make it minimal: just a "Reply" text link and "Open" (transcript). Left-click on the overlay background still dismisses.

### 4. Reply box clear on open

`_load_convo()` already calls `self._convo_reply.clear()` but the bug suggests it's not working, or the convo view is reusing stale state. Investigate and fix — ensure the reply input buffer is empty every time we transition to CONVO.

### 5. Picker sizing

The picker can't be crammed into the user's configured overlay width/height — it needs room for the conversation list. Options:

Use a larger fixed size for the picker view only. When switching to picker, temporarily resize the window (e.g. 500x400 minimum). When leaving picker, restore to normal width. The picker's ScrolledWindow should have a min-content-height so the list is actually usable.

### 6. Picker keyboard navigation

The picker has Ctrl+N/P for list navigation and Tab to focus the text input, but they're not wired up. Add a key controller to the picker widget that handles:
- `Ctrl+N` / `Down`: select next row
- `Ctrl+P` / `Up`: select previous row
- `Tab`: move focus to text input
- `Enter`: submit (already wired)

### 7. Remove `aside reply` CLI command

`aside reply <id>` (bare, no text) currently sends `{"cmd":"reply",...}` to the overlay. Change it to send `{"cmd":"convo",...}` instead (same as `aside view`). Then remove `handle_reply()` from the window and the REPLY state. `aside reply <id> "text"` (with text) still sends directly to the daemon as before.

Actually simpler: just make bare `aside reply <id>` an alias for `aside view <id>`.

## Out of scope

- Mic button / open transcript action buttons (future feature)
- Image support
- Fractional scaling tweaks
