# aside

a desktop LLM assistant for Wayland. ask questions, get answers, launch tools, and never lose focus on what you're doing.

![demo](demo.gif) ![demo](demo2.gif)

- **overlay** — C layer-shell surface. streams tokens in real time, auto-dismisses. hover to keep it, right-click to cancel.
- **voice** — STT via faster-whisper, TTS via Kokoro. talk to it, it talks back.
- **actions bar** — mic, transcript, and reply buttons after every response.
- **input popup** — GTK4 window with conversation history. continue one or start fresh.

## tools

aside ships with shell, memory, and web search built in. drop a Python file with a `TOOL_SPEC` + `run()` into a plugins directory and the daemon picks it up automatically.

the tool system is flexible enough to do real work — spawn background workers, run scripts, hit APIs, whatever you need.

![demo](demo4.gif)

the demo shows a custom [wreccless](https://github.com/scottstav/wreccless) plugin.

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

![demo](demo3.gif)

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

## theming

the overlay is fully customizable via `~/.config/aside/config.toml`:

```toml
[overlay]
font = "JetBrains Mono 12"
width = 700
max_lines = 40
corner_radius = 12

[overlay.colors]
background = "#1a1b26e6"    # RGBA hex (last 2 digits = alpha)
foreground = "#c0caf5ff"
border = "#414868ff"
accent = "#7aa2f7ff"
```

voice, TTS, model, plugins, and storage are all configurable too — see [config reference](docs/configuration.md).

## install

```bash
git clone https://github.com/scottstav/aside.git
cd aside
make install
systemctl --user enable --now aside-daemon aside-overlay
```

optional extras:

```bash
make install-extras-voice  # faster-whisper + VAD
make install-extras-tts    # kokoro TTS
make install-extras-gtk    # input popup
```

## docs

| | |
|---|---|
| [Installation](docs/install.md) | dependencies, build, AUR |
| [Usage](docs/usage.md) | CLI reference |
| [Configuration](docs/configuration.md) | config options |
| [Plugins](docs/plugins.md) | plugin API |
| [Architecture](docs/architecture.md) | system design |

MIT
