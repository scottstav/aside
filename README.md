# aside

Wayland-native LLM desktop assistant with streaming overlay, voice I/O, and a plugin system.

## Features

- **LLM-agnostic** -- uses [LiteLLM](https://github.com/BerriAI/litellm) so you can talk to Anthropic, OpenAI, Google, Ollama, and dozens of other providers with the same interface
- **Wayland overlay** -- a C11 layer-shell surface that streams responses in real time with smooth scroll and fade animations
- **GTK4 input popup** -- lightweight text entry with conversation history picker
- **Voice input** -- wake-word detection (openwakeword), speech-to-text (faster-whisper), and VAD-based auto-send
- **Text-to-speech** -- Kokoro synthesis with sentence-level streaming and code/URL filtering
- **Plugin system** -- drop a Python file with `TOOL_SPEC` + `run()` into a directory and the daemon picks it up automatically
- **Waybar integration** -- custom module showing status, token usage, and cost
- **Conversation persistence** -- full message history stored as JSON, resumable across sessions

## Quick Start

```bash
git clone https://github.com/scottstav/aside.git
cd aside
make install
```

Copy the example config and set your API key:

```bash
cp ~/.config/aside/config.toml.example ~/.config/aside/config.toml
# Edit config.toml -- at minimum set model.name
export ANTHROPIC_API_KEY="sk-..."   # or OPENAI_API_KEY, etc.
```

Start the services:

```bash
systemctl --user enable --now aside-daemon aside-overlay
```

Send a query:

```bash
aside query "what time is it in Tokyo?"
```

Or open the input window:

```bash
aside-input
```

### Optional extras

```bash
make install-extras-tts    # text-to-speech (kokoro)
make install-extras-voice  # voice input (openwakeword, faster-whisper)
make install-extras-gtk    # GTK4 input window (PyGObject)
```

## CLI Reference

### `aside`

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

### `aside-input`

GTK4 text entry popup. Opens a lightweight input window with conversation history picker. Pass `-c ID` to pre-select a conversation.

### `aside-actions`

GTK4 layer-shell action bar providing quick-access buttons for common daemon commands.

### `aside-status`

Waybar custom module. Reads the daemon's `status.json` and prints waybar-compatible JSON (`text`, `tooltip`, `class`) to stdout. Shows model name, cost tracking, and activity status.

## Configuration

All configuration lives in `~/.config/aside/config.toml`. The example config documents every option:

| Section          | What it controls                                    |
|------------------|-----------------------------------------------------|
| `[model]`        | LLM provider and model name, system prompt          |
| `[input]`        | Terminal emulator for input window                   |
| `[voice]`        | Wake word, STT model, silence detection              |
| `[tts]`          | Voice model, speed, text filtering                   |
| `[overlay]`      | Font, dimensions, colors, animation timing           |
| `[storage]`      | Conversation and archive directories                 |
| `[plugins]`      | Additional plugin directories                        |
| `[notifications]`| Commands to run on reply/listen events               |
| `[status]`       | Waybar signal number                                 |

See [`data/config.toml.example`](data/config.toml.example) for the full reference.

## Plugins

A plugin is a single Python file with two things: a `TOOL_SPEC` dict and a `run()` function.

```python
# plugins/hello.py

TOOL_SPEC = {
    "name": "hello",
    "description": "Say hello to someone",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Who to greet"},
        },
        "required": ["name"],
    },
}

def run(name: str) -> str:
    return f"Hello, {name}!"
```

Drop it into `~/.local/lib/aside/plugins/` or any directory listed in `plugins.dirs` in your config. The daemon loads it on next startup.

The `TOOL_SPEC` follows the OpenAI function-calling schema. `run()` receives keyword arguments matching the parameters and returns a string (or a dict with `{"type": "image", "data": ..., "media_type": ...}` for images).

Built-in tools: `clipboard`, `shell`, `memory`. Example plugins: `screenshot`, `web_search`, `fetch_url`.

## Architecture

```
                  aside-input (GTK4)    aside query "..."
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
      +-------------+        | (C / Wayland)    |
                              +------------------+
                                reads status.json
                                + overlay socket
```

The **daemon** is the central process. It listens on a Unix socket for commands (`query`, `cancel`, `stop_tts`, `listen`, `mute`/`unmute`), dispatches queries through LiteLLM with tool execution, and optionally runs voice input and TTS in background threads.

The **overlay** is a standalone C program using wlr-layer-shell. It reads configuration from `~/.config/aside/overlay.conf` (written by the daemon on startup) and receives streaming text deltas over its own Unix socket.

**Clients** (`aside` CLI, `aside-input` GTK4 window) connect to the daemon socket to send commands. `aside-status` reads the status file directly for waybar integration.

## Dependencies

### Required

| Dependency          | Purpose                          |
|---------------------|----------------------------------|
| Python >= 3.11      | Daemon and CLI                   |
| litellm             | LLM provider abstraction         |
| wayland-client      | Overlay Wayland connection        |
| wayland-protocols   | Layer-shell protocol (build)      |
| cairo               | Overlay 2D rendering              |
| pango               | Overlay text layout               |
| json-c              | Overlay JSON parsing              |
| meson + ninja       | Overlay build system              |

### Optional

| Dependency          | Purpose                           | Install target            |
|---------------------|-----------------------------------|---------------------------|
| kokoro              | Text-to-speech synthesis          | `make install-extras-tts` |
| sounddevice         | TTS audio output                  | `make install-extras-tts` |
| soundfile           | TTS audio file handling           | `make install-extras-tts` |
| openwakeword        | Wake word detection               | `make install-extras-voice`|
| faster-whisper      | Speech-to-text                    | `make install-extras-voice`|
| webrtcvad-wheels    | Voice activity detection          | `make install-extras-voice`|
| PyGObject + GTK4    | Input window                      | `make install-extras-gtk` |
| grim + slurp        | Screenshot plugin                 | system package            |

## Supported LLM Providers

Any provider supported by LiteLLM works out of the box. Set `model.name` in your config using the `provider/model` format:

| Provider   | Example model name                  | Env variable          |
|------------|-------------------------------------|-----------------------|
| Anthropic  | `anthropic/claude-sonnet-4-6`       | `ANTHROPIC_API_KEY`   |
| OpenAI     | `openai/gpt-4o`                     | `OPENAI_API_KEY`      |
| Google     | `gemini/gemini-2.0-flash`           | `GEMINI_API_KEY`      |
| Ollama     | `ollama/llama3`                     | (local, no key)       |
| Groq       | `groq/llama-3.1-70b-versatile`     | `GROQ_API_KEY`        |
| Together   | `together_ai/meta-llama/...`       | `TOGETHER_API_KEY`    |
| Mistral    | `mistral/mistral-large-latest`     | `MISTRAL_API_KEY`     |

See the [LiteLLM docs](https://docs.litellm.ai/docs/providers) for the full list.

## Arch Linux (AUR)

A `PKGBUILD` is included for Arch Linux users:

```bash
makepkg -si
```

## License

MIT -- see [LICENSE](LICENSE).
