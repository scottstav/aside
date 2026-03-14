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
| `aside reply ID --mic` | Continue a conversation via voice capture |
| `aside input` | Open the conversation picker in the overlay |
| `aside view ID` | View a conversation in the overlay |
| `aside ls [-n LIMIT]` | List recent conversations (default: 20) |
| `aside show ID` | Print a full conversation transcript |
| `aside open ID` | Open the conversation transcript |
| `aside rm ID` | Delete a conversation |
| `aside cancel` | Cancel the running query |
| `aside stop-tts` | Stop TTS playback |
| `aside status` | Print daemon status as JSON |
| `aside daemon` | Start the daemon in the foreground |

Conversation IDs can be short prefixes (e.g. the 7-char IDs shown by `aside ls`).

## `aside reply ID`

When called with just an ID (no text), opens the overlay's inline reply input for that conversation. Add text to reply directly from the terminal.

## `aside input`

Opens the overlay's conversation picker. Select an existing conversation or start a new one.

- `Enter` — submit
- `Shift+Enter` — newline
- `Escape` — close
- `Ctrl+N` / `Ctrl+P` — navigate conversation list
- `Tab` — move focus to text input

## `aside status`

Waybar custom module. Reads the daemon's `status.json` and prints waybar-compatible JSON to stdout. Shows model name, cost tracking, and activity status.

## Conversation management

Conversations are stored as JSON in `~/.local/state/aside/conversations/`. By default, a new query continues the most recent conversation. Use `--new` to start fresh.

Open any conversation transcript with `aside open ID`.
