# Model Management & Config Cleanup

## Problem

No way to discover available models or switch models without editing config.toml and restarting. Additionally, the daemon re-reads config.toml from disk on every query to check for model changes — unnecessary complexity.

## Design

### Config cleanup: load once, mutate in memory

Config loads once at daemon startup. All runtime-mutable state (model, speak_enabled) lives in memory and is changed only via socket commands. No more disk reads per query.

**Delete:**
- `Daemon._reload_model()` and `self._config_path`
- `state._read_model_from_config()`
- `StatusState.reload_model(config_path)`
- `StatusState.reload_speak_enabled()`

**`send_query`** reads `config["model"]["name"]` directly — already does, just remove the `_reload_model()` call preceding it.

### New module: `aside/models.py`

- `available_providers() -> list[str]` — returns provider names that have a key set (checks env vars via `keyring._PROVIDER_TO_ENV`, then keyring via `keyring.get_key()`).
- `available_models() -> dict[str, list[str]]` — for each keyed provider, pulls models from `litellm.models_by_provider[provider_key]`. Filters out non-chat models (embed, image, tts, audio, whisper, dall-e, imagen). Normalizes all names to `provider/model` format. Deduplicates. Returns `{provider: sorted_list}`.

Provider name mapping (keyring provider -> litellm registry key):
- `anthropic` -> `anthropic`
- `openai` -> `openai`
- `gemini` -> `gemini`
- `groq` -> `groq`
- `mistral` -> `mistral`
- `cohere` -> `cohere_chat`
- `together` -> `together_ai`
- `deepseek` -> `deepseek`

### New CLI commands

**`aside models`** — lists available models grouped by provider, marks current model with `*`. Connects to daemon socket (`get_model` action) for current model; falls back to config.toml if daemon is down.

**`aside model set <name>`** — sends `set_model` action to daemon socket. Runtime only, not persisted.

### New daemon socket actions

- `get_model` — returns JSON `{"model": "anthropic/claude-haiku-4-5"}`. Requires the socket handler to write a response back to the client (currently fire-and-forget).
- `set_model` — updates `self.config["model"]["name"]` and `self.status` model field in memory. Next query uses it.

### CLI output format

```
anthropic
  anthropic/claude-3-5-haiku-latest
  anthropic/claude-3-5-sonnet-latest
* anthropic/claude-haiku-4-5
  anthropic/claude-sonnet-4-6

gemini
  gemini/gemini-1.5-flash
  gemini/gemini-2.5-pro
```
