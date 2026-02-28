# Usage & CLI Reference

## `aside`

The main CLI. All subcommands talk to the daemon over a Unix socket.

| Command | Description |
|---------|-------------|
| `aside query TEXT` | Send a query to the daemon |
| `aside query --mic` | Send a query via one-shot voice capture |
| `aside query --new TEXT` | Force a new conversation |
| `aside query -c ID TEXT` | Continue a specific conversation |
| `aside reply ID [TEXT]` | Continue a conversation by ID (prompts for input if no text given) |
| `aside reply ID --gui` | Continue a conversation in the GTK input popup |
| `aside reply ID --mic` | Continue a conversation via voice capture |
| `aside ls [-n LIMIT]` | List recent conversations (default: 20) |
| `aside show ID` | Print a full conversation transcript |
| `aside open ID` | Export conversation to markdown and open it |
| `aside rm ID` | Delete a conversation |
| `aside cancel` | Cancel the running query |
| `aside stop-tts` | Stop TTS playback |
| `aside status` | Print daemon status as JSON |
| `aside daemon` | Start the daemon in the foreground |

Conversation IDs can be short prefixes (e.g. the 7-char IDs shown by `aside ls`).

## `aside-input`

GTK4 text entry popup. Opens a lightweight input window with conversation history picker. Pass `-c ID` to pre-select a conversation.

- `Enter` — submit
- `Shift+Enter` — newline
- `Escape` — close
- `Ctrl+N` / `Ctrl+P` — navigate conversation list
- `Tab` — move focus to text input

## `aside-actions`

GTK4 layer-shell action bar. Appears below the overlay after a response completes. Provides quick-access buttons for voice reply, open transcript, and text reply.

Auto-dismisses after 5 seconds of inactivity.

## `aside-status`

Waybar custom module. Reads the daemon's `status.json` and prints waybar-compatible JSON to stdout. Shows model name, cost tracking, and activity status.

## Conversation management

Conversations are stored as JSON in `~/.local/state/aside/conversations/`. By default, a new query continues the most recent conversation. Use `--new` to start fresh.

Export any conversation to markdown with `aside open ID`.
