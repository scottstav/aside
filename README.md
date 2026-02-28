# aside

a desktop LLM assistant for Wayland. ask it something with your voice or keyboard, it streams the answer onto a floating overlay, then fades away.

![demo](demo.gif)

voice input, follow-up questions, reply button, live transcript — it all just works.

## tools

aside ships with shell, memory, and web search built in. drop a Python file with a `TOOL_SPEC` + `run()` into a plugins directory and the daemon picks it up automatically.

the tool system is flexible enough to do real work — spawn background workers, run scripts, hit APIs, whatever you need.

![demo](demo4.gif)

i use [wreckless](https://github.com/scottstav/wreckless) for heavier stuff like multi-file refactors. more tool configs in [my dots](https://github.com/scottstav/dotfiles) if you're curious.

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

the CLI makes scripting and integration easy.

![demo](demo2.gif)

```bash
# models
aside models                    # list what's available
aside model set gemini/gemini-2.5-pro  # switch on the fly
aside model exclude openai/o1   # hide deprecated models

# querying
aside query "what time is it in tokyo"
aside query --mic               # voice input
aside reply abc123 "tell me more"

# state
aside status                    # daemon status as JSON
aside ls                        # recent conversations
aside show <id>                 # print conversation
aside open <id>                 # open as markdown

# voice
aside toggle-tts                # toggle text-to-speech
aside stop-tts                  # stop playback
aside cancel                    # cancel running query
```

### waybar

aside integrates with waybar out of the box — status icon updates in real time as the model thinks, uses tools, and responds.

![demo](demo3.gif)

```json
{
    "custom/aside": {
        "exec": "aside-status",
        "return-type": "json",
        "signal": 12,
        "interval": "once",
        "on-click": "aside-input",
        "on-click-right": "aside toggle-tts"
    }
}
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
