# TODO

## Refactoring

- [ ] Extract shared socket send helper — cli.py, window.py, query.py all implement connect-send-close independently
- [ ] Extract shared user text extraction — duplicated in state.py (twice) and cli.py
- [ ] Cache ConversationStore in window.py — instantiated fresh 4 times
- [ ] Extract shared base widget for picker/reply input — nearly identical TextView setup, key handling, CSS
- [ ] Break up `send_query` (240 lines, 16 params) — separate overlay IO, TTS, conversation persistence
- [ ] Break up `_mic_capture` closure — 77 lines nested inside async method
- [ ] Consolidate error handling in `send_query` — 4 identical except blocks
- [ ] `_dispatch` in app.py — consider dispatch dict instead of if/elif chain

## Constants / Magic Values

- [ ] Centralize socket names ("aside.sock", "aside-overlay.sock") — scattered across 6 files
- [ ] Centralize default model string — repeated 4 times
- [ ] Use `Pango.EllipsizeMode.END` instead of raw `3` in picker.py
- [ ] Fix width default mismatch — window.py defaults to 400, config.py says 600
- [ ] Move hardcoded markdown code block color (#2a2a2a) into theme system

## Bugs (low priority)

- [ ] `_send_overlay` in cli.py: overlay socket not leaked but not using context manager either
- [ ] `send_query`: overlay socket opened before try block — exception between open and try leaks it
- [ ] `connect_submit` must be called before `connect_expand` in ReplyInput — undocumented ordering dep
- [ ] Circular data flow: overlay reads conversation JSON that daemon writes with no file locking

## Build / Packaging

- [ ] Remove phantom system deps from PKGBUILDs (python-tiktoken, python-openai, etc.) — already in pip venv
- [ ] Check if python-cairo is actually needed as a runtime dep
- [ ] Pin gtk4-layer-shell version in Ubuntu build instructions
- [ ] .SRCINFO is stale — regenerate on next release

## Tests

- [ ] overlay/window.py has no behavioral tests — state machine, keyboard, dismiss timer, command dispatch
- [ ] `_dispatch` routing untested
- [ ] Socket buffer parsing (`_handle_connection`) untested
- [ ] Replace `time.sleep` in test_daemon.py with threading.Event barriers
- [ ] Move `TestDaemonModelActions` from test_cli.py to test_daemon.py

## Performance

- [ ] Move `import cairo` out of `accent_bar._draw()` — runs every frame
- [ ] Move `import struct` out of listener.py capture loop
