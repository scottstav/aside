# Overlay Modes: User Speech vs Agent Response

## Problem

1. No visual feedback when mic capture starts — user doesn't know aside is listening
2. Interim transcriptions during capture are discarded — user can't see their words
3. No visual distinction between user speech and agent response in the overlay

## Design

### Overlay Protocol

Add a `"mode"` field to `CMD_OPEN`:

```json
{"cmd": "open", "mode": "user", "conv_id": "..."}
{"cmd": "open", "mode": "agent", "conv_id": "..."}
```

`"mode"` defaults to `"agent"` when omitted (backwards compatible).

The mode controls the overlay's accent bar color:
- `"agent"` — existing `accent_color` (default: `#D4714A`, warm orange)
- `"user"` — new `user_accent_color` (default: `#5B8DEF`, soft blue)

### C Overlay Changes

**config.h / config.c:**
- Add `uint32_t user_accent_color` to `overlay_config`
- Default: `0x5B8DEFff`
- Parse `user_accent_color` in `config_set`

**socket.h / socket.c:**
- Add `char mode[8]` to `overlay_command`
- Parse `"mode"` field in `parse_command`

**main.c:**
- Store `current_mode` (0 = agent, 1 = user)
- Set mode on `CMD_OPEN` based on `cmd.mode`

**render.h / render.c:**
- Add `uint32_t accent_override` param to `renderer_draw`
- When non-zero, use it instead of `cfg->accent_color`

### Python Changes

**aside/voice/listener.py:**
- Add `on_interim` callback param to `capture_one_shot` and `_do_capture`
- Call `on_interim(interim_text)` each time interim transcription runs (every ~2s)
- Callback is optional (default `None`)

**aside/daemon.py — `_mic_capture` thread:**
1. Connect to overlay socket
2. Send `{"cmd": "open", "mode": "user", "conv_id": conv_id}`
3. Define callback: `on_interim` sends `{"cmd": "replace", "data": text}` to overlay
4. Call `capture_one_shot(config, on_interim=callback)`
5. Close overlay socket when capture finishes
6. Then `start_query` opens overlay again with `"mode": "agent"` (existing flow)

**aside/query.py — `send_query`:**
- Add `"mode": "agent"` to the existing `CMD_OPEN` call (explicit, not strictly required since it defaults)

### Flow

```
User runs: aside query --mic
  → daemon receives {action: "query", mic: true}
  → _mic_capture thread:
      1. overlay ← {"cmd": "open", "mode": "user"}     accent = blue
      2. overlay ← {"cmd": "replace", "data": "Hello"}  interim transcript
      3. overlay ← {"cmd": "replace", "data": "Hello world"}
      4. capture done → close overlay socket
  → start_query("Hello world", conv_id):
      1. overlay ← {"cmd": "open", "mode": "agent"}    accent = orange
      2. overlay ← {"cmd": "text", "data": "..."}      streaming response
      3. overlay ← {"cmd": "done"}
```

### Make dev target

Also fix: add `aside-actions` wrapper script to `make dev` target so actions bar works.
