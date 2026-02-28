# Keyring API Key Retrieval

Desktop-native API key management: KWallet, GNOME Keyring, EnvironmentFile fallback.

## Problem

API keys are currently set via environment variables or a runtime cache file.
Systemd user services don't inherit shell env vars, so users must either use
`systemctl --user edit` overrides or export vars before starting the daemon.
Desktop keyrings are the standard Linux mechanism for storing secrets.

## Key Retrieval Priority

For each provider key, on daemon startup:

1. **Environment variable** — explicit env always wins (includes EnvironmentFile)
2. **KWallet** — `kwalletcli-getentry -f aside -e <provider>-api-key`
3. **GNOME Keyring** — `secret-tool lookup service aside provider <provider>`
4. **Runtime cache** — existing JSON cache in `$XDG_RUNTIME_DIR/aside-api-keys`

EnvironmentFile (`~/.config/aside/env`) is loaded by systemd before the process
starts, so those vars appear as regular env vars (step 1).

## Keyring Secret Naming

### KWallet

- Folder: `aside`
- Entry: `<provider>-api-key` (e.g. `anthropic-api-key`)

### GNOME Keyring

- Attributes: `service=aside`, `provider=<provider>`
- Label: `aside: <provider> API key`

### Provider Name Mapping

| Env var            | Provider  |
|--------------------|-----------|
| ANTHROPIC_API_KEY  | anthropic |
| OPENAI_API_KEY     | openai    |
| GEMINI_API_KEY     | gemini    |
| GROQ_API_KEY       | groq      |
| MISTRAL_API_KEY    | mistral   |
| COHERE_API_KEY     | cohere    |
| TOGETHER_API_KEY   | together  |
| DEEPSEEK_API_KEY   | deepseek  |

## CLI Commands

```
aside set-key <provider> [key]   # store key (reads stdin if key omitted)
aside get-key <provider>         # print masked key for debugging
```

`set-key` tries KWallet first, then GNOME Keyring, then writes to
`~/.config/aside/env` as fallback.

## Implementation

### New file: `aside/keyring.py`

- `_kwallet_available()` — checks `kwalletcli-getentry` on PATH
- `_gnome_available()` — checks `secret-tool` on PATH
- `get_key(provider)` — try KWallet, then GNOME Keyring, return key or None
- `set_key(provider, key)` — store in first available backend, return backend name
- `load_keyring_keys()` — iterate `_API_KEY_VARS`, call `get_key()` for missing vars

Uses subprocess calls only — no Python keyring dependencies.

### Modified: `aside/daemon.py`

Call `load_keyring_keys()` between `_restore_api_keys()` and `_cache_api_keys()`.

### Modified: `aside/cli.py`

Add `set-key` and `get-key` subcommands.

### Modified: `data/aside-daemon.service`

Add `EnvironmentFile=-%h/.config/aside/env` (dash prefix = don't fail if missing).

### Modified: `docs/configuration.md`, `docs/install.md`

Document priority chain, keyring setup, CLI commands, env file.
