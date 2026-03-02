# aside

A desktop LLM assistant for Wayland. Ask questions, get answers, launch tools, and never lose focus on what you're doing.

[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/scottstav) [![Bitcoin](https://img.shields.io/badge/BTC-Donate-f7931a?logo=bitcoin&logoColor=white)](#donate) [![Monero](https://img.shields.io/badge/XMR-Donate-ff6600?logo=monero&logoColor=white)](#donate)

![demo](screenshots/demo1.gif) ![demo](screenshots/demo2.gif)

- **overlay** — C layer-shell surface. Streams tokens in real time. Reply or open full transcript with inline actions. Left click to dismiss, right-click to cancel query, middle click to mute TTS. **Very** customizable.
- **voice** — STT via faster-whisper, TTS via Piper (optional add-ons).
- **input popup** — GTK4 window with conversation history. Continue one or start fresh.


Bind `aside query --mic` to a hotkey and start talking. Aside detects silence and automatically sends your query. 

## tools

aside ships with a memory tool built in. Drop a Python file with a `TOOL_SPEC` + `run()` into a tool directory and the daemon picks it up automatically. See `examples/tools/` for reference implementations.

The tool system is flexible enough to do real work — run scripts, search files, open applications, etc, even create new tools.

![demo](screenshots/demo3.gif)

the demo shows a tool for launching [wreccless](https://github.com/scottstav/wreccless) workers.

## any LLM

[LiteLLM](https://github.com/BerriAI/litellm) under the hood — Claude, GPT, Gemini, Ollama, whatever. aside auto-detects which providers are available based on your API keys.

## API keys

keys are stored securely with a sane fallback chain:

1. **environment variables** — checked first
2. **GNOME Keyring** (via `secret-tool`) — if available
3. **KWallet** (via `kwalletcli`) — if available
4. **`~/.config/aside/env`** — plaintext fallback (mode 0600)

```bash
aside set-key anthropic sk-ant-...
aside set-key openai sk-...
```

## CLI

everything goes through the CLI, which makes it easy to script, integrate with pickers, or wire into status bars.

![demo](screenshots/demo4.gif)

```bash
# models — auto-detects what's available based on your API keys
aside models
aside model set gemini/gemini-2.5-pro
aside model exclude openai/o1

# querying — rapid follow-ups auto-attach to the same conversation
aside query "what time is it in tokyo"
aside query --mic
aside reply abc123 "tell me more"

# state
aside status                    # JSON, great for status bars
aside ls                        # recent conversations
aside show <id>                 # print conversation
aside open <id>                 # open as markdown

# voice
aside toggle-tts
aside stop-tts
aside cancel
```

## theming and customization

Highly configurable via `~/.config/aside/config.toml`, overlay position, colors, fonts, size.

```toml
[model]
name = "anthropic/claude-haiku-4-5"

[input]
font = "Iosevka 12"

[storage]
archive_dir = "~/Dropbox/LLM/Chats"

[tools]
dirs = ["~/.config/aside/tools"]

[overlay]
position = "top-center"
font = "Iosevka 12"
max_lines = 5
corner_radius = 8
border_width = 1
accent_height = 4
scroll_duration = 200
fade_duration = 400
width = 450
margin_top = 5
padding_top = 2.5

[overlay.colors]
background = "#1a1c1ee6"
foreground = "#d4d4d4ff"
border = "#5a4a3aff"
accent = "#5b9a6a"
user_accent = "#a07048"

[voice]
enabled = false
stt_model = "base"
stt_device = "cpu"
smart_silence = true
silence_timeout = 2.5
no_speech_timeout = 3.0

[tts]
enabled = false
speed = 1.0
filter = {skip_code_blocks = true, skip_urls = true}
```

voice, TTS, model, plugins, and storage are all configurable too — see [config reference](docs/configuration.md).

## install

### arch linux (AUR)

```bash
yay -S aside
aside set-key anthropic sk-ant-...
systemctl --user enable --now aside-daemon aside-overlay

# optional add-ons
sudo aside enable-stt   # speech-to-text (faster-whisper, ~100MB)
sudo aside enable-tts   # text-to-speech (piper-tts, ~60MB voice model)
```

### manual

```bash
git clone https://github.com/scottstav/aside.git
cd aside
make install
aside set-key anthropic sk-ant-...
systemctl --user enable --now aside-daemon aside-overlay

# optional add-ons
sudo aside enable-stt   # speech-to-text
sudo aside enable-tts   # text-to-speech
```

## docs

| | |
|---|---|
| [Installation](docs/install.md) | dependencies, build, AUR |
| [Usage](docs/usage.md) | CLI reference |
| [Configuration](docs/configuration.md) | config options |
| [Plugins](docs/plugins.md) | plugin API |
| [Architecture](docs/architecture.md) | system design |

## donate

<a id="donate"></a>

| | |
|---|---|
| Ko-fi | [ko-fi.com/scottstav](https://ko-fi.com/scottstav) |
| BTC | `bc1q7xeyf4k0ud3akgch8svjwmdmeucr5mxx8lt4h6` |
| XMR | `864dQBZ5LTDhcUFX2P5mxV4ubjxLNFvCa4p8xLGd9b3XAEbeXXGrUa6M78eftfUpQkFk81BHrSHeCGXoQCXMcRGRTu8cM4u` |

MIT
