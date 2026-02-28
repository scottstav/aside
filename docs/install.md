# Installation

## Quick install

```bash
git clone https://github.com/scottstav/aside.git
cd aside
make install
```

This builds the C overlay and installs the Python package into a venv.

Copy the example config and set your API key:

```bash
cp ~/.config/aside/config.toml.example ~/.config/aside/config.toml
# Edit config.toml — at minimum set model.name
aside set-key anthropic sk-ant-...   # or: aside set-key openai sk-...
```

See [configuration.md](configuration.md#api-key-configuration) for all key storage options (keyring, env file, env vars).

Start the services:

```bash
systemctl --user enable --now aside-daemon aside-overlay
```

## Optional extras

```bash
make install-extras-tts    # text-to-speech (kokoro)
make install-extras-voice  # voice input (openwakeword, faster-whisper)
make install-extras-gtk    # GTK4 input window (PyGObject)
```

## Building from source

### C overlay

```bash
cd overlay && meson setup build --prefix=/usr && ninja -C build
```

### Python package

```bash
python -m venv .venv && source .venv/bin/activate && pip install -e .
```

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

## Arch Linux (AUR)

A `PKGBUILD` is included:

```bash
makepkg -si
```

## Supported LLM providers

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
