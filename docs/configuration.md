# Configuration

aside is configured via a TOML file at `$XDG_CONFIG_HOME/aside/config.toml` (usually `~/.config/aside/config.toml`). All keys are optional — sensible defaults are used for anything you don't set.

An annotated example is included at [`data/config.toml.example`](../data/config.toml.example).

## `[model]`

LLM model selection. Uses [LiteLLM](https://docs.litellm.ai/) provider/model format.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `name` | string | `"anthropic/claude-sonnet-4-6"` | Model identifier (e.g. `openai/gpt-4o`, `ollama/llama3`) |
| `system_prompt` | string | `""` | Extra text appended to the built-in system prompt |

## `[input]`

Input popup window settings.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `terminal` | string | `"foot -e"` | Terminal emulator command. Must accept `-e` to run a command |
| `font` | string | `""` | Pango font description for the input popup. Falls back to `overlay.font` when empty |

## `[voice]`

Speech-to-text capture via faster-whisper.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Enable voice input |
| `stt_model` | string | `"base"` | faster-whisper model size: `tiny`, `base`, `small`, `medium`, `large` |
| `stt_device` | string | `"cpu"` | Inference device: `"cpu"` or `"cuda"` |
| `smart_silence` | bool | `true` | Automatically end recording after silence (VAD-based) |
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

## `[tts.filter]`

Controls which parts of a response are read aloud.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `skip_code_blocks` | bool | `true` | Skip fenced code blocks |
| `skip_urls` | bool | `true` | Skip URLs |

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
| `signal` | int | `12` | SIGRTMIN+N signal number sent to waybar on state changes |
