# Installation

## Quick install

You need a C toolchain and Wayland dev libraries (likely already present on any Wayland desktop):

```bash
# Arch
pacman -S wayland wayland-protocols cairo pango json-c pipewire gtk4 gtk4-layer-shell

# Debian/Ubuntu
apt install libwayland-dev wayland-protocols libcairo2-dev libpango1.0-dev libjson-c-dev libpipewire-0.3-dev libgtk-4-dev libgtk4-layer-shell-dev
```

Then install aside with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install aside-assistant
```

`uv` auto-downloads Python 3.12 if your system Python is too new (e.g. Arch 3.14). All dependencies — including voice and TTS — are installed automatically.

Set your API key and start the services:

```bash
aside set-key anthropic sk-ant-...   # or: aside set-key openai sk-...
systemctl --user enable --now aside-daemon aside-overlay
```

See [configuration.md](configuration.md#api-key-configuration) for all key storage options (keyring, env file, env vars).

## From source

```bash
git clone https://github.com/scottstav/aside.git
cd aside
make install
systemctl --user enable --now aside-daemon aside-overlay
```

This builds the C overlay and Python package into a venv at `~/.local/lib/aside/venv/`.

## Dev install

The C overlay and Python package build together via meson-python:

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e .
```

## Dependencies

### System (C overlay)

| Dependency          | Purpose                          |
|---------------------|----------------------------------|
| wayland-client      | Overlay Wayland connection        |
| wayland-protocols   | Layer-shell protocol (build)      |
| cairo               | Overlay 2D rendering              |
| pango               | Overlay text layout               |
| json-c              | Overlay JSON parsing              |
| gtk4 + gtk4-layer-shell | Input window, reply bar      |
| meson + ninja       | Build system (pulled in by meson-python) |

### Python (installed automatically)

| Dependency          | Purpose                          |
|---------------------|----------------------------------|
| Python >= 3.11, < 3.13 | Daemon and CLI               |
| litellm             | LLM provider abstraction         |
| faster-whisper      | Speech-to-text                    |
| kokoro              | Text-to-speech synthesis          |
| PyGObject           | GTK4 bindings                     |

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
