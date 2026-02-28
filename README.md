# aside

Wayland-native LLM assistant. You talk to it (keyboard or mic), it streams the response onto a floating overlay on your desktop, and it goes away when it's done.

![Overlay streaming a response](screenshots/overlay-streaming.png)

## Overlay

C11 layer-shell surface. Streams text token-by-token as it comes back from the LLM. Auto-scrolls, fades content at the edges, and dismisses itself after a few seconds. Hover to keep it around. Left-click to dismiss. Right-click to cancel mid-stream.

![Overlay text detail](screenshots/overlay-closeup.png)

The accent bar at the top is orange when the LLM is responding, green when it's listening to your mic. When nothing's happening, the overlay doesn't exist — no window, no tray icon.

## Actions bar

When a response finishes, a small bar appears below the overlay with three buttons — mic (voice reply), open (view the transcript), and reply (inline text input). Goes away on its own after 5 seconds.

![Actions bar](screenshots/actions-bar.png)

## Voice

Speech-to-text via faster-whisper. You talk, it transcribes in real time on the overlay, and auto-sends when you stop. TTS via Kokoro — responses are synthesized sentence-by-sentence and played back as text streams in. Middle-click the overlay to kill the audio without stopping the text.

## Input popup

GTK4 window for typing queries. Shows recent conversations so you can pick one to continue.

![Input popup](screenshots/input-popup.png)

## Waybar

Custom module that shows the model name, cost, and what the daemon is doing. Click it to open the input popup.

![Waybar module](screenshots/waybar-module.png)

## LLM support

Uses [LiteLLM](https://github.com/BerriAI/litellm) — Claude, GPT-4o, Gemini, Ollama, Groq, Mistral, whatever. One config line to switch.

## Plugins

Drop a Python file with a `TOOL_SPEC` dict and a `run()` function into the plugins directory. That's it. Built-in tools: shell, screenshot (sends the image to the LLM), web search, persistent memory, clipboard.

## Install

```bash
git clone https://github.com/scottstav/aside.git
cd aside
make install
systemctl --user enable --now aside-daemon aside-overlay
```

Voice, TTS, and GTK input are separate:

```bash
make install-extras-voice  # faster-whisper + VAD
make install-extras-tts    # kokoro
make install-extras-gtk    # input popup
```

## Docs

| | |
|---|---|
| [Installation](docs/install.md) | Dependencies, build steps, AUR |
| [Usage & CLI](docs/usage.md) | All commands |
| [Configuration](docs/configuration.md) | Config reference |
| [Plugins](docs/plugins.md) | Plugin API |
| [Architecture](docs/architecture.md) | System design, sockets, data flow |

## License

MIT
