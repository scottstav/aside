# Installation

## Quick install

System deps:

```bash
# Arch
pacman -S gtk4 gtk4-layer-shell python-gobject

# Debian/Ubuntu
apt install python3-venv python3-dev libgtk-4-dev gobject-introspection \
    libgirepository1.0-dev python3-gi python3-gi-cairo gir1.2-gtk-4.0 \
    meson ninja-build valac

# gtk4-layer-shell (not yet packaged in Ubuntu — build from source)
git clone https://github.com/wmww/gtk4-layer-shell.git /tmp/gtk4-layer-shell
cd /tmp/gtk4-layer-shell && meson setup build && ninja -C build && sudo ninja -C build install
sudo ldconfig
```

Then:

```bash
git clone https://github.com/scottstav/aside.git
cd aside
make install
```

This installs the Python package into a venv at `~/.local/lib/aside/venv/` and sets up systemd units.

Set your API key and start the services:

```bash
aside set-key anthropic sk-ant-...   # or: aside set-key openai sk-...
systemctl --user enable --now aside-daemon aside-overlay
```

See [configuration.md](configuration.md#api-key-configuration) for all key storage options (keyring, env file, env vars).

## Dev install

```bash
python -m venv .venv && source .venv/bin/activate && pip install -e .
```

## Dependencies

### System

| Dependency              | Purpose                          |
|-------------------------|----------------------------------|
| GTK4                    | Overlay UI toolkit               |
| gtk4-layer-shell        | Wayland layer-shell integration  |
| PyGObject (gi bindings) | Python GTK4 bindings             |

### Python (installed automatically into venv)

| Dependency             | Purpose                          |
|------------------------|----------------------------------|
| Python >= 3.11         | Daemon, CLI, overlay             |
| litellm                | LLM provider abstraction         |
| mistune                | Markdown rendering               |
| faster-whisper (opt)   | Speech-to-text                   |
| piper-tts (opt)        | Text-to-speech synthesis         |

### Optional

| Dependency          | Purpose                           |
|---------------------|-----------------------------------|
| grim + slurp        | Screenshot plugin                 |

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
