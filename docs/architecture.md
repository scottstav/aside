# Architecture

## Overview

```
                  aside input (GTK4)    aside query "..."
                       |                       |
                       +-------+-------+-------+
                               |
                          Unix socket
                               |
                       +-------v-------+
                       |    Daemon     |
                       |  (daemon.py)  |
                       +--+----+----+--+
                          |    |    |
             +------------+    |    +------------+
             |                 |                 |
      +------v------+  +------v------+  +-------v------+
      | LiteLLM     |  | Voice       |  | TTS          |
      | query.py    |  | listener    |  | tts.py       |
      +------+------+  +-------------+  +--------------+
             |
      +------v------+
      | Plugins     |        +------------------+
      | plugins.py  |        | aside-overlay    |
      +-------------+        | (GTK4 / Wayland) |
                              +------------------+
                                overlay socket
```

## Components

The **daemon** is the central process. It listens on a Unix socket for commands (`query`, `cancel`, `stop_tts`, `listen`, `mute`/`unmute`), dispatches queries through LiteLLM with tool execution, and optionally runs voice input and TTS in background threads.

The **overlay** is a GTK4 application using gtk4-layer-shell. It reads configuration from `~/.config/aside/config.toml` and receives streaming text, reply inputs, and conversation views over its own Unix socket. It handles streaming display, inline reply, full conversation history, and the conversation picker — all in a single process.

**Clients** (`aside` CLI) connect to the daemon socket to send commands. The CLI also sends display commands to the overlay socket (e.g. `aside input`, `aside view`, `aside reply`). `aside status` reads the status file directly for waybar integration.

## Socket protocol

### Daemon socket

Located at `$XDG_RUNTIME_DIR/aside.sock`. The CLI sends JSON commands here.

### Overlay socket

Located at `$XDG_RUNTIME_DIR/aside-overlay.sock`. JSON commands, newline-delimited:

| Command | Description |
|---------|-------------|
| `{"cmd":"open"}` | Show overlay, clear text |
| `{"cmd":"text","data":"..."}` | Append text (streaming) |
| `{"cmd":"done"}` | Fade out |
| `{"cmd":"clear"}` | Dismiss immediately |
| `{"cmd":"replace","data":"..."}` | Replace all text |
| `{"cmd":"thinking"}` | Show thinking state |
| `{"cmd":"listening"}` | Show listening state |
| `{"cmd":"input"}` | Open conversation picker |
| `{"cmd":"reply","conversation_id":"..."}` | Open reply input for conversation |
| `{"cmd":"convo","conversation_id":"..."}` | Show full conversation history |

## Data flow

1. User sends a query (CLI, overlay picker, voice)
2. Daemon receives it on the Unix socket
3. Daemon sends `open` to the overlay
4. Daemon streams the query through LiteLLM
5. Each response chunk is forwarded to the overlay via `text` commands
6. Tool calls are executed inline, results fed back to the LLM
7. When the response finishes, daemon sends `done` to the overlay
8. Overlay lingers briefly, then fades out

## File locations

| Path | Purpose |
|------|---------|
| `~/.config/aside/config.toml` | User configuration |
| `~/.local/state/aside/conversations/` | Conversation JSON files |
| `~/.local/state/aside/memory.md` | Persistent assistant memory |
| `~/.local/state/aside/status.json` | Current daemon status |
| `~/.local/lib/aside/plugins/` | User plugin directory |
| `$XDG_RUNTIME_DIR/aside.sock` | Daemon socket |
| `$XDG_RUNTIME_DIR/aside-overlay.sock` | Overlay socket |
