# Configuration

All configuration lives in `~/.config/aside/config.toml`. Copy the example to get started:

```bash
cp ~/.config/aside/config.toml.example ~/.config/aside/config.toml
```

## Sections

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

## Full reference

See [`data/config.toml.example`](../data/config.toml.example) for every option with inline documentation.

### Model

```toml
[model]
name = "anthropic/claude-sonnet-4-6"   # LiteLLM format: provider/model
system_prompt = ""                      # optional system prompt
```

### Voice

```toml
[voice]
enabled = false
wake_word_model = ""           # path to openwakeword .onnx model
wake_word_threshold = 0.5
pre_roll_seconds = 0.5         # audio buffered before wake word
stt_model = "base"             # faster-whisper model size
stt_device = "cpu"             # "cpu" or "cuda"
smart_silence = true           # end recording on silence detection
silence_timeout = 2.5          # seconds of silence before auto-send
no_speech_timeout = 3.0        # seconds with no speech before cancel
force_send_phrases = ["send it", "that's it"]
```

### Text-to-speech

```toml
[tts]
enabled = false
model = "af_heart"             # kokoro voice model
speed = 1.0
lang = "a"                     # kokoro language code

[tts.filter]
skip_code_blocks = true        # don't read code blocks aloud
skip_urls = true               # don't read URLs aloud
```

### Overlay

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
scroll_duration = 200          # ms
fade_duration = 400            # ms

[overlay.colors]
background = "#1a1b26e6"       # RGBA hex (last two = alpha)
foreground = "#c0caf5ff"
border = "#414868ff"
accent = "#7aa2f7ff"
```

### Storage

```toml
[storage]
conversations_dir = ""         # default: $XDG_STATE_HOME/aside/conversations
archive_dir = ""               # default: $XDG_STATE_HOME/aside/archive
```

### Plugins

```toml
[plugins]
dirs = []                      # additional plugin directories to scan
```

### Notifications

```toml
[notifications]
reply_command = ""             # command to run when a reply arrives
listen_command = ""            # command to run when listening starts
```

### Status

```toml
[status]
signal = 12                    # SIGRTMIN+N signal for waybar updates
```
