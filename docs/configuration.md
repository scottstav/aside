# Configuration

All configuration lives in a single TOML file:

```
~/.config/aside/config.toml
```

(Or `$XDG_CONFIG_HOME/aside/config.toml` if `XDG_CONFIG_HOME` is set.)

Copy the example to get started:

```bash
cp /usr/share/aside/config.toml.example ~/.config/aside/config.toml
```

Only uncomment the values you want to change. Aside uses sensible defaults for everything.

Changes take effect on daemon restart (`systemctl --user restart aside-daemon`).

---

## Model

```toml
[model]
name = "anthropic/claude-sonnet-4-6"
system_prompt = ""
```

| Option | Default | Description |
|--------|---------|-------------|
| `name` | `anthropic/claude-sonnet-4-6` | LiteLLM model identifier. Format: `provider/model-name`. Examples: `openai/gpt-4o`, `ollama/llama3`, `gemini/gemini-pro` |
| `system_prompt` | `""` | Extra text appended to the built-in system prompt. The built-in prompt handles conciseness and desktop context — use this for personal preferences |

## Input

```toml
[input]
terminal = "foot -e"
```

| Option | Default | Description |
|--------|---------|-------------|
| `terminal` | `foot -e` | Terminal emulator used to launch the input popup. Must accept `-e` to run a command. Works with `foot`, `alacritty`, `kitty`, etc. |

## Voice

Requires `make install-extras-voice` for STT dependencies.

```toml
[voice]
enabled = false
stt_model = "base"
stt_device = "cpu"
smart_silence = true
silence_timeout = 2.5
no_speech_timeout = 3.0
force_send_phrases = ["send it", "that's it"]
max_capture_seconds = 60
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Enable voice input (STT via faster-whisper) |
| `stt_model` | `base` | faster-whisper model size: `tiny`, `base`, `small`, `medium`, or `large`. Larger = more accurate, slower |
| `stt_device` | `cpu` | Whisper inference device: `cpu` or `cuda` |
| `smart_silence` | `true` | Dynamically adjust silence timeout based on transcript content. Waits longer mid-sentence, shorter after sentence-ending punctuation |
| `silence_timeout` | `2.5` | Base seconds of silence before auto-sending |
| `no_speech_timeout` | `3.0` | Seconds without any detected speech before cancelling capture |
| `force_send_phrases` | `["send it", "that's it"]` | Phrases that trigger an immediate send, bypassing silence detection |
| `max_capture_seconds` | `60` | Hard maximum recording duration |

## Text-to-Speech

Requires `make install-extras-tts` for Kokoro dependencies.

```toml
[tts]
enabled = false
model = "af_heart"
speed = 1.0
lang = "a"

[tts.filter]
skip_code_blocks = true
skip_urls = true
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Enable TTS output via Kokoro |
| `model` | `af_heart` | Kokoro voice model name (e.g. `af_heart`, `af_bella`) |
| `speed` | `1.0` | Speech playback speed multiplier |
| `lang` | `a` | Kokoro language code (`a` = American English) |
| `filter.skip_code_blocks` | `true` | Don't read code blocks aloud |
| `filter.skip_urls` | `true` | Don't read URLs aloud |

## Overlay

Controls the floating overlay that displays responses.

```toml
[overlay]
font = "Sans 13"
width = 600
max_lines = 40
margin_top = 10
padding_x = 20
padding_y = 16
corner_radius = 12
border_width = 2
accent_height = 3
scroll_duration = 200
fade_duration = 400

[overlay.colors]
background = "#1a1b26e6"
foreground = "#c0caf5ff"
border = "#414868ff"
accent = "#7aa2f7ff"
```

### Layout

| Option | Default | Description |
|--------|---------|-------------|
| `font` | `Sans 13` | Pango font description for overlay text |
| `width` | `600` | Overlay width in pixels |
| `max_lines` | `40` | Maximum visible lines before the overlay scrolls |
| `margin_top` | `10` | Distance from the top of the screen in pixels |
| `padding_x` | `20` | Horizontal padding inside the overlay |
| `padding_y` | `16` | Vertical padding inside the overlay |
| `corner_radius` | `12` | Border corner radius in pixels |
| `border_width` | `2` | Border thickness in pixels |
| `accent_height` | `3` | Height of the colored accent line at the top. Set to `0` to disable |

### Animation

| Option | Default | Description |
|--------|---------|-------------|
| `scroll_duration` | `200` | Text scroll animation duration in milliseconds |
| `fade_duration` | `400` | Fade-out animation duration in milliseconds |

### Colors

All colors are RGBA hex strings. The last two hex digits control alpha (transparency). `ff` = fully opaque, `00` = fully transparent.

| Option | Default | Description |
|--------|---------|-------------|
| `background` | `#1a1b26e6` | Overlay background (default is dark with ~90% opacity) |
| `foreground` | `#c0caf5ff` | Text color |
| `border` | `#414868ff` | Border color |
| `accent` | `#7aa2f7ff` | Top accent line color (shown during agent responses) |
| `user_accent` | *(unset)* | Alternate accent color shown during voice capture. Falls back to `accent` if not set |

## Storage

```toml
[storage]
conversations_dir = ""
archive_dir = ""
```

| Option | Default | Description |
|--------|---------|-------------|
| `conversations_dir` | `""` | Custom path for conversation files. Empty = `$XDG_STATE_HOME/aside/conversations` |
| `archive_dir` | `""` | Custom path for archived conversations. Empty = `$XDG_STATE_HOME/aside/archive` |

## Plugins

```toml
[plugins]
dirs = []
```

| Option | Default | Description |
|--------|---------|-------------|
| `dirs` | `[]` | Additional directories to scan for plugin files. See [Plugins](plugins.md) for the plugin API |

Built-in tools are always loaded from `aside/tools/` inside the package.

## Notifications

```toml
[notifications]
reply_command = ""
listen_command = ""
```

| Option | Default | Description |
|--------|---------|-------------|
| `reply_command` | `""` | Shell command to run when a response arrives (e.g. a notification sound) |
| `listen_command` | `""` | Shell command to run when voice listening starts |

## Status

```toml
[status]
signal = 12
```

| Option | Default | Description |
|--------|---------|-------------|
| `signal` | `12` | SIGRTMIN+N signal number sent to waybar for status updates. The `aside-status` waybar module listens on this signal |

---

## API key configuration

Aside needs an API key for your chosen LLM provider. Keys are resolved in this order:

1. **Environment variable** — set directly or via systemd EnvironmentFile
2. **KWallet** — queried via `kwalletcli-getentry`
3. **GNOME Keyring** — queried via `secret-tool`
4. **Runtime cache** — `$XDG_RUNTIME_DIR/aside-api-keys` (survives daemon restarts)

### Supported provider keys

| Variable | When needed |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic models (`anthropic/claude-*`) |
| `OPENAI_API_KEY` | OpenAI models (`openai/gpt-*`) |
| `GEMINI_API_KEY` | Google Gemini models |
| `GROQ_API_KEY` | Groq models |
| `MISTRAL_API_KEY` | Mistral models |
| `DEEPSEEK_API_KEY` | DeepSeek models |
| `TOGETHER_API_KEY` | Together AI models |
| `COHERE_API_KEY` | Cohere models |

For local models via Ollama, no API key is needed — just set `model.name = "ollama/llama3"`.

### Using the CLI (recommended)

```bash
aside set-key anthropic sk-ant-...
aside set-key openai sk-...
```

This stores the key in KWallet or GNOME Keyring (whichever is available), falling back to `~/.config/aside/env`. To verify:

```bash
aside get-key anthropic
# anthropic: sk-a...xyz
```

### Using a desktop keyring manually

**KWallet:**

```bash
echo -n "sk-..." | kwalletcli-setentry -f aside -e anthropic-api-key
```

**GNOME Keyring:**

```bash
echo -n "sk-..." | secret-tool store --label='aside: anthropic API key' service aside provider anthropic
```

### Using an environment file

Create `~/.config/aside/env` (mode 0600):

```
ANTHROPIC_API_KEY=sk-...
```

The systemd unit loads this file automatically via `EnvironmentFile`. For shell use, source it: `. ~/.config/aside/env`.

### Using environment variables directly

```bash
export ANTHROPIC_API_KEY="sk-..."
```

Or in a systemd override (`systemctl --user edit aside-daemon`):

```ini
[Service]
Environment=ANTHROPIC_API_KEY=sk-...
```

## File paths

| Path | Purpose |
|------|---------|
| `~/.config/aside/config.toml` | Main configuration file |
| `~/.config/aside/env` | API key environment file (loaded by systemd) |
| `~/.config/aside/overlay.conf` | Generated overlay config (written by daemon on startup) |
| `~/.local/state/aside/conversations/` | Conversation JSON files |
| `~/.local/state/aside/archive/` | Archived conversations |
| `~/.local/state/aside/usage.jsonl` | Token usage log |
| `~/.local/state/aside/status.json` | Current daemon status (read by waybar module) |
| `$XDG_RUNTIME_DIR/aside.sock` | Daemon Unix socket |
| `$XDG_RUNTIME_DIR/aside-overlay.sock` | Overlay Unix socket |
| `$XDG_RUNTIME_DIR/aside-api-keys` | Cached API keys |
