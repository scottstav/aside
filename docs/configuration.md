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
font = ""
```

| Option | Default | Description |
|--------|---------|-------------|
| `terminal` | `foot -e` | Terminal emulator used to launch the input popup. Must accept `-e` to run a command. Works with `foot`, `alacritty`, `kitty`, etc. |
| `font` | `""` | Font for the input window text area. Empty = inherit from overlay font |

## Voice

```toml
[voice]
enabled = false
stt_model = "base"
stt_device = "cpu"
smart_silence = true
silence_timeout = 2.5
no_speech_timeout = 3.0
force_send_phrases = ["send it", "that's it"]
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

## Text-to-Speech

TTS is optional. Install it with:

```bash
sudo aside enable-tts
```

This installs `piper-tts` into the aside venv and downloads a default English voice model. To remove it later: `sudo aside disable-tts`.

```toml
[tts]
enabled = false
model = ""
speed = 1.0
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Enable TTS output via Piper |
| `model` | `""` | Path to a Piper `.onnx` voice model file. Empty = use the default model installed by `enable-tts`. Download additional voices from [Piper voices](https://huggingface.co/rhasspy/piper-voices) |
| `speed` | `1.0` | Speech playback speed multiplier (>1 = faster, <1 = slower) |

## Overlay

Controls the floating overlay that displays responses.

```toml
[overlay]
font = "Sans 13"
width = 400
max_height = 500
position = "top-center"
margin_top = 10
opacity = 0.95
dismiss_timeout = 5.0

[overlay.colors]
background = "#0f0f14"
foreground = "#e2e8f0"
border = "#2a2a3a"
accent = "#8b5cf6"
user_accent = "#22d3ee"
```

### Layout

| Option | Default | Description |
|--------|---------|-------------|
| `font` | `Sans 13` | Pango font description for overlay text |
| `width` | `400` | Overlay width in pixels |
| `max_height` | `500` | Maximum overlay height in pixels. Applies to streaming, convo view, and picker |
| `position` | `top-center` | Overlay position on screen: `top-left`, `top-center`, `top-right`, `bottom-left`, `bottom-center`, `bottom-right`, `center` |
| `margin_top` | `10` | Top margin in pixels |
| `margin_right` | `0` | Right margin in pixels |
| `margin_bottom` | `0` | Bottom margin in pixels |
| `margin_left` | `0` | Left margin in pixels |
| `padding_x` | `20` | Horizontal padding inside the overlay |
| `padding_y` | `16` | Vertical padding inside the overlay |
| `corner_radius` | `12` | Border corner radius in pixels |
| `border_width` | `2` | Border thickness in pixels |
| `accent_height` | `3` | Height of the colored accent line at the top. Set to `0` to disable |

### Behavior

| Option | Default | Description |
|--------|---------|-------------|
| `opacity` | `0.95` | Background opacity (0.0 = fully transparent, 1.0 = fully opaque) |
| `dismiss_timeout` | `5.0` | Seconds before the overlay auto-dismisses after a response completes. Set to `0` to disable auto-dismiss |

### Animation

| Option | Default | Description |
|--------|---------|-------------|
| `scroll_duration` | `200` | Text scroll animation duration in milliseconds |
| `fade_duration` | `400` | Fade-out animation duration in milliseconds |

### Colors

All colors are RGBA hex strings. The last two hex digits control alpha (transparency). `ff` = fully opaque, `00` = fully transparent.

| Option | Default | Description |
|--------|---------|-------------|
| `background` | `#0f0f14` | Overlay background |
| `foreground` | `#e2e8f0` | Text color |
| `border` | `#2a2a3a` | Border color |
| `accent` | `#8b5cf6` | LLM accent — accent bar during thinking/streaming, LLM message border, buttons |
| `user_accent` | `#22d3ee` | User accent — accent bar during listening, user message color, reply input border |

## Storage

```toml
[storage]
archive_dir = ""
```

| Option | Default | Description |
|--------|---------|-------------|
| `archive_dir` | `""` | Custom path for conversation files. Empty = `$XDG_STATE_HOME/aside/conversations` |

## Tools

```toml
[tools]
dirs = []
```

| Option | Default | Description |
|--------|---------|-------------|
| `dirs` | `[]` | Additional directories to scan for tool plugin files. See [Plugins](plugins.md) for the plugin API |

Built-in tools are always loaded from `aside/tools/` inside the package. User tools in `~/.config/aside/tools/` are also loaded automatically.

## Status

```toml
[status]
signal = 12
```

| Option | Default | Description |
|--------|---------|-------------|
| `signal` | `12` | SIGRTMIN+N signal number sent to waybar for status updates. The `aside status` waybar module listens on this signal |

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
| `~/.config/aside/tools/` | User tool plugins |
| `~/.local/state/aside/conversations/` | Conversation JSON files |
| `~/.local/state/aside/usage.jsonl` | Token usage log |
| `~/.local/state/aside/status.json` | Current daemon status (read by waybar module) |
| `$XDG_RUNTIME_DIR/aside.sock` | Daemon Unix socket |
| `$XDG_RUNTIME_DIR/aside-overlay.sock` | Overlay Unix socket |
| `$XDG_RUNTIME_DIR/aside-api-keys` | Cached API keys |
