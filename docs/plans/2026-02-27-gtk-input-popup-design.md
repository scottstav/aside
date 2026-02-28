# GTK4 Layer-Shell Action Bar

## Problem

The C overlay's hand-rolled buttons and text input are inadequate: no hover effects, no cursor movement, no text wrapping, no clipboard, no readline keybindings, no visual focus indication. Reimplementing all of this in C against raw Wayland/Pango is a waste — every toolkit solves this already.

## Decision

Move ALL interactive UI (action buttons + text input) out of the C overlay into a separate GTK4 application (`aside-actions`) that uses `gtk4-layer-shell`. The C overlay becomes a pure text renderer. The GTK popup handles all user interaction.

## Architecture

```
C overlay streams text → CMD_DONE arrives
  → overlay spawns aside-actions with conv_id + geometry
  → C overlay keeps showing response text (stays visible)
  → GTK popup appears BELOW the text: [mic] [open] [reply]
  → user clicks reply → buttons hide, text input appears (same GTK surface)
  → on submit: sends query to daemon socket, GTK closes
  → daemon streams response → C overlay gets CMD_OPEN, GTK is already gone
  → Escape at any point → GTK closes, C overlay fades normally
```

The C overlay is now single-purpose: render streaming text, scroll, fade.

## aside-actions GTK Popup

- **Framework:** GTK4 + gtk4-layer-shell
- **Layer:** OVERLAY (same as C overlay)
- **Anchor:** TOP, centered horizontally
- **Positioning:** Margin-top = overlay margin + overlay current height. Width matches overlay.
- **Modes:** Starts in button mode, transitions to input mode on reply click.

### Button Mode

- Horizontal row of buttons: [mic] [open] [reply]
- Styled to match overlay: same background, font, accent color, rounded corners
- Hover effects, click feedback via CSS
- **open** button hidden if `xdg-open` not available (checked at startup)
- Clicking mic → sends `{"action":"query","conversation_id":"...","mic":true}` to daemon, closes
- Clicking open → runs `aside open CONV_ID`, closes
- Clicking reply → transitions to input mode

### Input Mode

- **Widget:** GtkTextView with word wrapping
- **Grows:** 1 line → up to 5 lines as text wraps, then scrolls internally
- **Submit:** Enter sends text. Shift+Enter for newline.
- **Cancel:** Escape returns to button mode. Double-Escape closes entirely.
- **Clipboard:** Ctrl+V pastes text. Image paste saves to `/tmp`, path sent with query.
- **Editing:** All GTK text editing comes free — Ctrl+A/E/B/F/W/U/K, selection, etc.
- **Focus:** Auto-focused on transition, blinking cursor, highlighted border

### Arguments

```
aside-actions --conv-id UUID --width 600 --margin-top 60
```

Reads overlay config from `~/.config/aside/overlay.conf` for colors/font.

### Communication

On submit, connects to `$XDG_RUNTIME_DIR/aside.sock` and sends:

```json
{"action": "query", "text": "...", "conversation_id": "UUID"}
```

For image attachments:

```json
{"action": "query", "text": "describe this", "conversation_id": "UUID", "images": ["/tmp/aside-paste-xxx.png"]}
```

## Changes to C Overlay

- **Remove:** `input_active`, `input_buf`, `input_len`, `on_key()`, `draw_input_box()`, `draw_buttons()`, `handle_button_click()`
- **Remove:** xkbcommon keyboard handling, pointer hit-testing for buttons
- **Remove:** `button_rect` struct, `action_buttons` array, `show_buttons` flag
- **Add:** On CMD_DONE, fork/exec `aside-actions` with conv_id and current geometry (width, margin-top + rendered height), then stay visible (no dismiss)
- **Keep:** Text rendering, scroll, fade/linger, pointer scroll, click-to-dismiss, right-click-to-cancel

## Changes to Daemon

- Handle optional `images` array in query action (pass to LLM as image content blocks)

## Dependencies

- `gtk4` (already on most desktops)
- `gtk4-layer-shell` (Arch: `gtk4-layer-shell`, Fedora: `gtk4-layer-shell`, Ubuntu: `libgtk4-layer-shell-dev`)

## Build

New executable target in `overlay/meson.build`:

```meson
dep_gtk4 = dependency('gtk4')
dep_layer_shell = dependency('gtk4-layer-shell-0')

executable('aside-actions',
  'src/actions.c',
  dependencies: [dep_gtk4, dep_layer_shell],
  install: true)
```
