# GTK4 Overlay Port Design

## Motivation

Eliminate the C build (meson/ninja, platform-specific quirks like Ubuntu libm linking)
and unify the UI stack on Python/GTK4 for easier future development (markdown
rendering, images, richer interactions).

## Architecture Overview

Three separate UI processes (C overlay, aside-input, aside-reply) become a single
Python/GTK4 process. The daemon remains its own process. The two-socket IPC model
is preserved.

```
CLI / keybinds ──► aside.sock (daemon)
                       │
                       ▼
                   daemon process
                       │
                       ▼
              aside-overlay.sock (overlay)
                       │
                       ▼
                 GTK4 overlay process
                 (one window, all UI states)
```

## Process Model

- **Daemon** — separate process, unchanged. Hub for CLI, overlay, plugins.
- **Overlay** — single long-running Python/GTK4 process. Replaces the C overlay,
  aside-input, and aside-reply. Runs as a systemd user service.

## Window & Layer-Shell

Single `Gtk.Window` with gtk4-layer-shell:

- **Layer:** OVERLAY
- **Anchoring:** configurable (top-right default), same config keys as today
- **Keyboard mode:** ON_DEMAND — grabs keyboard when reply input or picker is active
- **Namespace:** `"aside"`
- **Size:** width from config (default 600px), height dynamic with a max that grows
  in conversation view (~2x compact max)
- **Fractional scaling:** handled by GTK4 natively, verified with layer-shell
- **Lifecycle:** always alive, show/hide via `set_visible()`. No create/destroy per interaction.

## Component Architecture

```
aside/overlay/
├── __init__.py
├── app.py              # Adw.Application, socket listener, GTK setup
├── window.py           # Main window, layer-shell config, state transitions
├── accent_bar.py       # AccentBar widget — animated top bar
├── message_view.py     # MessageView widget — single message with markdown
├── conversation.py     # ConversationHistory — scrollable list of MessageViews
├── reply_input.py      # ReplyInput widget — text entry box
├── picker.py           # ConversationPicker — list of past conversations
├── markdown.py         # Markdown → TextBuffer+TextTags renderer (mistune)
└── css.py              # CSS builder from config colors/fonts
```

### Widget Hierarchy

```
Window (Gtk.Window + layer-shell)
 └── Gtk.Box (vertical)
      ├── AccentBar            ← always visible, all states
      └── Gtk.Stack            ← switches between views
           ├── "stream"  → ConversationHistory (1 msg) + ActionButtons
           ├── "convo"   → ConversationHistory (all msgs) + ReplyInput
           └── "picker"  → ConversationPicker
```

### Component Reuse

- **ConversationHistory** is the same widget in stream and convo views. Stream mode
  has one MessageView; expanding populates the rest.
- **MessageView** renders a single message (user or LLM) with markdown. Styled by
  role: user messages show the user's accent color, LLM messages show the LLM color.
- **ReplyInput** is the same component in reply and convo views.
- **AccentBar** sits outside the Stack — persistent across all views.

## State Machine

Five states, driven by socket commands and user actions:

```
         ┌──────────────────────────────────────────────┐
         │                                              │
    ┌────▼────┐   {"cmd":"open"}   ┌──────────┐        │
    │  HIDDEN  │──────────────────►│ STREAMING │        │
    └────┬────┘                    └─────┬─────┘        │
         │                               │              │
         │  {"cmd":"input"}         {"cmd":"done"}      │
         │                               │              │
    ┌────▼────┐                    ┌─────▼─────┐        │
    │  PICKER  │──── Tab ─────────►│  DISPLAY   │       │
    └─────────┘                    └─────┬─────┘        │
                                         │              │
                                    Reply button        │
                                         │              │
                                   ┌─────▼─────┐       │
                                   │   REPLY    │       │
                                   └─────┬─────┘       │
                                         │              │
                                    Shift+Tab           │
                                         │              │
                                   ┌─────▼─────┐       │
                                   │   CONVO    │───────┘
                                   └───────────┘  Esc / send + done
```

| State       | Visible                                    | AccentBar     | Keyboard |
|-------------|-------------------------------------------|---------------|----------|
| HIDDEN      | Nothing                                    | —             | —        |
| STREAMING   | Single MessageView, text appending          | streaming     | No grab  |
| DISPLAY     | Single MessageView, action buttons          | idle (solid)  | No grab  |
| REPLY       | Single MessageView + ReplyInput             | idle (solid)  | Grabbed  |
| CONVO       | Full ConversationHistory + ReplyInput       | idle (solid)  | Grabbed  |
| PICKER      | ConversationPicker                         | idle (solid)  | Grabbed  |

Additional: `{"cmd":"thinking"}` and `{"cmd":"listening"}` change the AccentBar
animation within STREAMING without changing the state itself.

## Accent Bar

First-class component, not decoration. The primary UX feedback mechanism.

**Animated states:**
- **Idle** — solid bar in accent color
- **Thinking** — sweep/pulse animation
- **Listening** — waveform or breathing animation
- **Streaming** — subtle activity animation
- **Done** — fade to idle, then overlay dismisses

Implemented as a custom `Gtk.DrawingArea` with Cairo drawing and
`add_tick_callback` for animations.

## Socket Protocol

### Existing Commands (unchanged)

- `{"cmd":"open","mode":"user"|"voice"}` — show overlay, start streaming
- `{"cmd":"text","data":"..."}` — append streamed text
- `{"cmd":"done"}` — streaming finished
- `{"cmd":"clear"}` — dismiss immediately
- `{"cmd":"replace","data":"..."}` — replace all text
- `{"cmd":"thinking"}` — accent bar thinking animation
- `{"cmd":"listening"}` — accent bar listening animation

### New Commands

- `{"cmd":"input"}` — show the conversation picker
- `{"cmd":"reply","conversation_id":"..."}` — open CONVO view for a conversation
- `{"cmd":"convo","conversation_id":"..."}` — view a conversation (no reply focus)

### Removed

Pipe-based IPC (`hold_fd`, `reposition_fd`) eliminated — reply is now in the same
process as the overlay.

## CLI Commands

Every overlay capability is reachable from the CLI for scripting:

```
aside query "..."          # send query to daemon (existing)
aside input                # open conversation picker (new)
aside reply <convo-id>     # open reply to specific conversation (new)
aside view <convo-id>      # view a conversation (new)
aside dismiss              # clear/hide overlay (existing)
```

## Markdown Rendering

- **Library:** mistune (pure Python, fast, extensible)
- **Approach:** full re-parse of accumulated text on each `{"cmd":"text"}` chunk.
  Negligible overhead at LLM response volumes.
- **Config:** `overlay.markdown = true` (default). When false, plain text only.
- **v1 elements:** bold, italic, code spans, code blocks, headings, lists, links
- **Future:** images (extensible via TextTag + GdkPixbuf, not in v1)

Each markdown element maps to a named TextTag. Tags created once per TextBuffer
from config colors/fonts.

## Configuration

- Overlay reads `config.toml` directly via `aside.config.load_config()`.
- `overlay.conf` (generated INI file) is eliminated.
- New config keys: `overlay.markdown` (bool, default true).

## What Gets Deleted

**Removed entirely:**
- `overlay/` — C/meson directory (~1500 LOC)
- `aside/input/` — input window package
- `aside/reply/` — reply window package
- `aside-overlay.service` (replaced by new unit for Python overlay)

**Removed from pyproject.toml:**
- `aside-input` and `aside-reply` entry points

**Added:**
- `aside-overlay` entry point → `aside.overlay.app:main`
- `mistune` dependency

**Modified:**
- `aside/cli.py` — new subcommands, remove process spawning
- `aside/daemon.py` — remove overlay.conf generation, remove pipe IPC, send new
  socket commands instead of spawning processes
- Build/install docs — remove meson/ninja requirements

**Net effect:** ~1500 LOC C + ~800 LOC Python deleted, replaced with ~600-800 LOC
clean Python. No C build step.

## Testing Strategy

**Unit tests (pytest, no display):**
- markdown.py — correct TextTag positions/types, streaming chunks, disabled mode
- accent_bar.py — state transitions, animation callback lifecycle
- window.py — state machine transitions from socket command sequences
- conversation.py — history population, ordering, role-based styling
- picker.py — list population, selection, keyboard navigation
- css.py — CSS generation from config dicts

**Integration tests:**
- Socket protocol: send JSON commands, verify state changes
- Reply flow: submit via ReplyInput, verify query arrives at daemon socket

**Manual testing (VM with SPICE viewer):**
- Accent bar animations, view transitions, markdown rendering, fractional scaling
- Full flow: query → stream → reply → expand → conversation history
