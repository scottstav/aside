# Configuration

aside is configured via a TOML file at `$XDG_CONFIG_HOME/aside/config.toml` (usually `~/.config/aside/config.toml`). All keys are optional — sensible defaults are used for anything you don't set.

An annotated example is included at [`data/config.toml.example`](../data/config.toml.example).

## `[model]`

LLM model selection. Uses [LiteLLM](https://docs.litellm.ai/) provider/model format. If a model is set through the cli while the daemon is running, it will be changed for that daemon instance without a restart. A restart will revert back to this config setting.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `name` | string | `"anthropic/claude-sonnet-4-6"` | Model identifier (e.g. `openai/gpt-4o`, `ollama/llama3`) |
| `system_prompt` | string | `""` | Extra text appended to the built-in system prompt |
| `timeout` | int/float | `30` | LLM request timeout in seconds |

## `[input]`

Input popup window settings.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `font` | string | `""` | Pango font description for the input popup. Falls back to `overlay.font` when empty |

## `[voice]`

Speech-to-text capture via faster-whisper.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Enable voice input, togglable via cli without daemon restart. Reverts to this setting on restart. |
| `stt_model` | string | `"base"` | faster-whisper model size: `tiny`, `base`, `small`, `medium`, `large`. The model is downloaded on first voice capture after a daemon start. Changing this requires a daemon restart. |
| `stt_device` | string | `"cpu"` | Inference device: `"cpu"` or `"cuda"`. Changing this requires a daemon restart. |
| `smart_silence` | bool | `true` | Adjust silence timeout based on transcript content. When on, waits less after complete sentences (1.5s) and longer after mid-sentence words like "the" or "and" (3.5s). When off, always waits exactly `silence_timeout`. |
| `silence_timeout` | float | `2.5` | Seconds of silence before auto-sending the query |
| `no_speech_timeout` | float | `3.0` | Seconds with no speech detected before cancelling |
| `force_send_phrases` | array | `["send it", "that's it"]` | Spoken phrases that trigger an immediate send |

## `[tts]`

Text-to-speech playback via Piper.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Enable TTS playback of responses |
| `model` | string | `""` | Path to a Piper `.onnx` voice model. When empty, uses `/usr/share/piper-voices/en/en_US/lessac/medium/en_US-lessac-medium.onnx` |
| `speed` | float | `1.0` | Speech rate multiplier. Values above 1 are faster, below 1 slower |

## `[overlay]`

Wayland layer-shell overlay appearance and layout. Width is clamped to 200–2000 and max_lines to 1–50.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `font` | string | `"Sans 13"` | Pango font description |
| `width` | int | `600` | Overlay width in logical pixels (200–2000) |
| `max_lines` | int | `5` | Maximum visible lines of text (1–50) |
| `position` | string | `"top-center"` | Screen position: `top-left`, `top-center`, `top-right`, `bottom-left`, `bottom-center`, `bottom-right`, `center` |
| `margin_top` | int | `10` | Top margin in pixels |
| `margin_right` | int | `0` | Right margin in pixels |
| `margin_bottom` | int | `0` | Bottom margin in pixels |
| `margin_left` | int | `0` | Left margin in pixels |
| `padding_x` | int | `20` | Horizontal text padding in pixels |
| `padding_y` | int | `16` | Vertical text padding in pixels |
| `corner_radius` | int | `12` | Corner rounding radius in pixels |
| `border_width` | int | `2` | Border thickness in pixels |
| `accent_height` | int | `3` | Accent bar height in pixels (0 disables). Top bar for agent responses, bottom bar for user/mic mode |
| `scroll_duration` | int | `200` | Text scroll animation in milliseconds |
| `fade_duration` | int | `400` | Fade-out animation in milliseconds |

## `[overlay.colors]`

All colors use `#RRGGBBAA` hex format. The last two digits are alpha (e.g. `e6` is ~90% opaque, `ff` is fully opaque).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `background` | string | `"#1a1b26e6"` | Background fill |
| `foreground` | string | `"#c0caf5ff"` | Text color |
| `border` | string | `"#414868ff"` | Border color |
| `accent` | string | `"#7aa2f7ff"` | Accent bar color for agent responses |
| `user_accent` | string | `"#a07048ff"` | Accent bar color for user/mic mode |

## `[storage]`

Override default state directories. When empty, XDG defaults are used (`$XDG_STATE_HOME/aside/` or `~/.local/state/aside/`).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `conversations_dir` | string | `""` | Directory for conversation JSON state files. Default: `<state_dir>/conversations` |
| `archive_dir` | string | `""` | Directory for exported markdown transcripts. Default: `<state_dir>/archive` |

## `[tools]`

Plugin tool loading.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `dirs` | array | `[]` | Additional directories to scan for tool plugins |

## `[status]`

Status bar integration. The daemon sends a real-time signal on state changes so status bar modules (e.g. waybar custom modules) can refresh immediately.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `signal` | int | `12` | SIGRTMIN+N signal number sent to waybar for status updates |

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
