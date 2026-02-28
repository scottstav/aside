# CLI Actions & Overlay Interactivity

Replace notification-based actions with CLI commands and overlay buttons.

## Architecture

Three changes:

1. Expand CLI with conversation management commands
2. Add interactive buttons and text input to the overlay
3. Remove action notifications (keep error-only notifications)

Communication topology (unchanged, one addition):

```
CLI  ──────────▶  daemon (aside.sock)  ──────────▶  overlay (overlay.sock)
                        ▲                                   │
                        └───────────────────────────────────┘
                          cancel, stop_tts, query (NEW)
```

The daemon remains the single orchestrator. CLI and overlay are both clients.

## CLI Commands

```
aside query TEXT [-c ID] [--new]      # send text query
aside query --mic [-c ID] [--new]     # voice query (one-shot capture)
aside reply ID [TEXT] [--gui] [--mic] # continue conversation
aside cancel [ID]                     # cancel running query
aside ls                              # list conversations (id + first msg + age)
aside show ID                         # print transcript to stdout
aside open ID                         # export to .md temp file, xdg-open
aside rm ID                           # delete conversation file
aside stop-tts                        # stop TTS playback
aside status                          # print daemon status JSON
aside daemon                          # start daemon foreground
```

### reply behavior

- `aside reply ID` — TUI prompt in terminal (simple input)
- `aside reply ID "some text"` — send directly, no prompt
- `aside reply ID --gui` — open GTK input popup (existing aside-input)
- `aside reply ID --mic` — one-shot voice capture, transcribe, send
- TEXT and --mic are mutually exclusive
- --gui and --mic are mutually exclusive

### Stateless commands

`ls`, `show`, `open`, `rm` read/write conversation JSON files directly. No daemon communication.

### Voice capture

One-shot only: record until silence (VAD), transcribe (STT), send as text. No persistent wake-word listener (removed; easy to add back later as a daemon module since it's just another client of the query pipeline).

## Overlay Changes

### Conversation ID awareness

The `open` command gains a `conv_id` field:

```json
{"cmd": "open", "conv_id": "abc123"}
```

Overlay stores this and includes it in commands sent back to the daemon.

### Action buttons

Three buttons render at the bottom of the overlay after CMD_DONE (during linger):

| Button | Action |
|--------|--------|
| Mic | Send `{action: "query", conversation_id: ID, mic: true}` to daemon socket |
| Open | Fork+exec `aside open <conv_id>` (stateless, no daemon needed) |
| Reply | Switch overlay to input mode |

Rendered with Cairo, hit-tested against pointer position. Clicking any button cancels linger/fade.

### Built-in text input

When reply button is clicked:

1. Text input box appears at bottom of overlay (same visual style)
2. Keyboard focus via wl_keyboard
3. User types, real-time rendering (Cairo/Pango)
4. Backspace for basic editing
5. Enter: send query to daemon socket, dismiss overlay entirely. Overlay reappears when daemon starts streaming the response.
6. Escape: dismiss input box, return to button state (no query sent)

### Existing interactions preserved

- Left click on text area: dismiss
- Right click: cancel query
- Middle click: stop TTS
- Scroll: manual scroll
- Hover: pause fade

## Daemon Changes

- Accept `mic: true` in query commands — daemon does one-shot voice capture then processes as text query
- Send `conv_id` in `open` command to overlay
- Remove persistent VoiceListener (wake-word)
- One-shot voice capture is a standalone function usable by both daemon and CLI

## Notification Changes

- Remove `notify_final()` (no more action notifications)
- Remove `notify()` progress notifications
- Keep notify-send for errors only (missing API key, daemon crash, etc.)
- Remove `reply_command` and `listen_command` from config

## Cost Tracking Removal

- Remove `TOKEN_PRICES` dict and cost calculation
- Keep token count tracking (standard OpenAI `usage` response field)
- `usage.jsonl` logs `input_tokens`, `output_tokens`, `total_tokens` (no `cost_usd`)
- Status JSON shows token counts, not cost

## Testing Order

1. CLI commands: `ls`, `show`, `open`, `rm` (stateless, easy)
2. CLI `reply` (text mode, then --mic)
3. Notification removal (verify queries still work)
4. Overlay buttons (render after CMD_DONE, wire up actions)
5. Overlay text input (wl_keyboard, rendering, submit/escape)
6. Conv ID threading (daemon sends in open, overlay sends back with replies)

Each step independently testable in VM.
