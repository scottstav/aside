# CLI Actions & Overlay Interactivity — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace notification-based actions with CLI commands and interactive overlay buttons/text input.

**Architecture:** CLI and overlay are both clients of the daemon socket. New CLI commands for conversation management. Overlay gains action buttons (after CMD_DONE) and a built-in text input box. Notifications removed except for errors.

**Tech Stack:** Python (CLI/daemon), C11/Wayland/Cairo/Pango (overlay), wl_keyboard (text input), pytest (tests)

**Design doc:** `docs/plans/2026-02-27-cli-overlay-actions-design.md`

---

### Task 1: CLI `ls` command

List conversations with ID, first user message, and relative age.

**Files:**
- Modify: `aside/cli.py` — add `ls` subcommand and handler
- Modify: `aside/state.py` — `ConversationStore.list_recent()` already exists (line 101), may need to extract first user message
- Test: `tests/test_cli.py` — add argument parsing tests for `ls`

**Step 1: Write the failing test**

In `tests/test_cli.py`, add to the argument parsing test class:

```python
def test_ls_basic(self):
    args = self.parser.parse_args(["ls"])
    assert args.command == "ls"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -x -q -k test_ls_basic`
Expected: FAIL — no `ls` subcommand exists

**Step 3: Add `ls` subparser to `_build_parser()`**

In `aside/cli.py`, add after the existing subcommands:

```python
sub.add_parser("ls", help="List recent conversations")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -x -q -k test_ls_basic`
Expected: PASS

**Step 5: Write failing test for `_cmd_ls` output**

In `tests/test_cli.py`:

```python
class TestLs:
    def test_ls_empty(self, tmp_path, capsys):
        from aside.cli import _cmd_ls
        from aside.state import ConversationStore
        store = ConversationStore(str(tmp_path))
        _cmd_ls(store)
        assert capsys.readouterr().out == ""

    def test_ls_shows_conversations(self, tmp_path, capsys):
        from aside.cli import _cmd_ls
        from aside.state import ConversationStore
        store = ConversationStore(str(tmp_path))
        conv = store.get_or_create()
        conv["messages"].append({"role": "user", "content": "What is the weather?"})
        store.save(conv)
        _cmd_ls(store)
        out = capsys.readouterr().out
        assert conv["id"][:7] in out
        assert "What is the weather?" in out
```

**Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -x -q -k TestLs`
Expected: FAIL — `_cmd_ls` doesn't exist

**Step 7: Implement `_cmd_ls`**

In `aside/cli.py`:

```python
def _cmd_ls(args):
    """List recent conversations."""
    from aside.config import load_config, resolve_conversations_dir
    from aside.state import ConversationStore
    import json, os
    from datetime import datetime, timezone

    cfg = load_config()
    store = ConversationStore(resolve_conversations_dir(cfg))
    convos = store.list_recent(limit=20)

    for entry in convos:
        conv_id = entry["id"]
        path = store._path_for(conv_id)
        try:
            with open(path) as f:
                data = json.load(f)
            msgs = data.get("messages", [])
            first_user = next((m["content"] for m in msgs if m["role"] == "user"), "")
            if isinstance(first_user, list):
                first_user = next((p["text"] for p in first_user if p.get("type") == "text"), "")
            first_user = first_user[:60].replace("\n", " ")
        except (OSError, json.JSONDecodeError, KeyError):
            first_user = ""

        # Relative age
        mtime = os.path.getmtime(path)
        age_s = datetime.now(timezone.utc).timestamp() - mtime
        if age_s < 60:
            age = f"{int(age_s)}s ago"
        elif age_s < 3600:
            age = f"{int(age_s / 60)}m ago"
        elif age_s < 86400:
            age = f"{int(age_s / 3600)}h ago"
        else:
            age = f"{int(age_s / 86400)}d ago"

        print(f"{conv_id[:7]}  {age:>8}  {first_user}")
```

Note: The exact implementation may need to adapt to `list_recent()` return format and `_cmd_ls` signature (may need to accept `args` from argparse). Read the actual code to get the details right.

**Step 8: Run tests**

Run: `python -m pytest tests/test_cli.py -x -q -k TestLs`
Expected: PASS (may need to adjust test to match actual `_cmd_ls` signature)

**Step 9: Wire up handler in dispatch map and add to `_build_parser`**

Add `"ls": _cmd_ls` to the handler dict. Run full test suite.

**Step 10: Commit**

```bash
git add aside/cli.py tests/test_cli.py
git commit -m "feat: add aside ls command"
```

---

### Task 2: CLI `show` command

Print full conversation transcript to stdout.

**Files:**
- Modify: `aside/cli.py` — add `show` subcommand and handler
- Test: `tests/test_cli.py`

**Step 1: Write failing test**

```python
def test_show_parser(self):
    args = self.parser.parse_args(["show", "abc123"])
    assert args.command == "show"
    assert args.conversation_id == "abc123"
```

**Step 2: Run test, verify fail**

Run: `python -m pytest tests/test_cli.py -x -q -k test_show_parser`

**Step 3: Add subparser**

```python
p = sub.add_parser("show", help="Print conversation transcript")
p.add_argument("conversation_id")
```

**Step 4: Run test, verify pass**

**Step 5: Write failing test for output**

```python
class TestShow:
    def test_show_prints_transcript(self, tmp_path, capsys):
        from aside.state import ConversationStore
        store = ConversationStore(str(tmp_path))
        conv = store.get_or_create()
        conv["messages"] = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        store.save(conv)
        # Call _cmd_show with the conv id
        from aside.cli import _cmd_show
        # ... test prints user/assistant messages
```

**Step 6: Implement `_cmd_show`**

Load conversation JSON, print each message with role prefix. Format:

```
user: Hello
assistant: Hi there!
```

Tool messages shown as `tool(name): result`. Tool calls shown as `assistant: [calling tool_name]`.

**Step 7: Run tests, verify pass**

**Step 8: Wire up and commit**

```bash
git add aside/cli.py tests/test_cli.py
git commit -m "feat: add aside show command"
```

---

### Task 3: CLI `open` command

Export conversation to markdown temp file, open with xdg-open.

**Files:**
- Modify: `aside/cli.py` — add `open` subcommand and handler
- Test: `tests/test_cli.py`

**Step 1: Write failing test for parser**

```python
def test_open_parser(self):
    args = self.parser.parse_args(["open", "abc123"])
    assert args.command == "open"
    assert args.conversation_id == "abc123"
```

**Step 2: Run test, verify fail**

**Step 3: Add subparser**

```python
p = sub.add_parser("open", help="Open conversation in default viewer")
p.add_argument("conversation_id")
```

**Step 4: Run test, verify pass**

**Step 5: Write failing test for export**

```python
class TestOpen:
    def test_open_creates_markdown(self, tmp_path, monkeypatch):
        from aside.state import ConversationStore
        store = ConversationStore(str(tmp_path))
        conv = store.get_or_create()
        conv["messages"] = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        store.save(conv)
        # Mock subprocess.Popen to capture xdg-open call
        opened = []
        monkeypatch.setattr("subprocess.Popen", lambda args, **kw: opened.append(args))
        from aside.cli import _cmd_open
        # ... verify markdown file was created and xdg-open called
```

**Step 6: Implement `_cmd_open`**

Write conversation to `/tmp/aside-{conv_id[:8]}.md` in readable markdown format. Call `subprocess.Popen(["xdg-open", path])`.

**Step 7: Run tests, commit**

```bash
git add aside/cli.py tests/test_cli.py
git commit -m "feat: add aside open command"
```

---

### Task 4: CLI `rm` command

Delete a conversation file.

**Files:**
- Modify: `aside/cli.py` — add `rm` subcommand
- Test: `tests/test_cli.py`

**Step 1: Write failing test**

```python
def test_rm_parser(self):
    args = self.parser.parse_args(["rm", "abc123"])
    assert args.command == "rm"

class TestRm:
    def test_rm_deletes_conversation(self, tmp_path):
        from aside.state import ConversationStore
        store = ConversationStore(str(tmp_path))
        conv = store.get_or_create()
        store.save(conv)
        path = store._path_for(conv["id"])
        assert os.path.exists(path)
        from aside.cli import _cmd_rm
        # ... call rm, verify file deleted
```

**Step 2: Implement**

Load config, resolve path, delete `{conv_id}.json`. Print confirmation or error if not found.

**Step 3: Run tests, commit**

```bash
git add aside/cli.py tests/test_cli.py
git commit -m "feat: add aside rm command"
```

---

### Task 5: CLI `reply` command (text mode)

Continue a conversation by ID. TUI prompt by default, inline text as argument, `--gui` for GTK popup.

**Files:**
- Modify: `aside/cli.py` — add `reply` subcommand
- Test: `tests/test_cli.py`

**Step 1: Write failing test for parser**

```python
def test_reply_parser(self):
    args = self.parser.parse_args(["reply", "abc123"])
    assert args.command == "reply"
    assert args.conversation_id == "abc123"
    assert args.text is None
    assert not args.gui
    assert not args.mic

def test_reply_with_text(self):
    args = self.parser.parse_args(["reply", "abc123", "follow up question"])
    assert args.text == "follow up question"

def test_reply_gui(self):
    args = self.parser.parse_args(["reply", "abc123", "--gui"])
    assert args.gui

def test_reply_mic(self):
    args = self.parser.parse_args(["reply", "abc123", "--mic"])
    assert args.mic

def test_reply_text_and_mic_exclusive(self):
    with pytest.raises(SystemExit):
        self.parser.parse_args(["reply", "abc123", "text", "--mic"])
```

**Step 2: Add subparser with mutually exclusive group**

```python
p = sub.add_parser("reply", help="Continue a conversation")
p.add_argument("conversation_id")
input_group = p.add_mutually_exclusive_group()
input_group.add_argument("text", nargs="?", default=None)
input_group.add_argument("--mic", action="store_true")
p.add_argument("--gui", action="store_true")
```

Note: argparse mutual exclusion between positional and optional args is tricky. May need to validate in the handler instead. Read argparse docs and test.

**Step 3: Run tests, iterate until parser works**

**Step 4: Write failing test for `_cmd_reply` text mode**

```python
class TestReply:
    def test_reply_sends_query_with_conv_id(self, tmp_path, monkeypatch):
        sent = []
        monkeypatch.setattr("aside.cli._send", lambda msg: sent.append(msg))
        # Simulate args with text="follow up" and conversation_id="abc123"
        from aside.cli import _cmd_reply
        # ... verify sent message has conversation_id and text
```

**Step 5: Implement `_cmd_reply`**

```python
def _cmd_reply(args):
    text = args.text
    if text is None and not args.mic and not args.gui:
        # TUI prompt
        text = input(">>> ")
    if args.gui:
        # Launch GTK popup (aside-input with -c flag)
        subprocess.Popen(["aside-input", "-c", args.conversation_id])
        return
    if args.mic:
        _send({"action": "query", "conversation_id": args.conversation_id, "mic": True})
        return
    if text:
        _send({"action": "query", "text": text, "conversation_id": args.conversation_id})
```

**Step 6: Run tests, commit**

```bash
git add aside/cli.py tests/test_cli.py
git commit -m "feat: add aside reply command"
```

---

### Task 6: Add `--mic` to `query` command

Make `TEXT` and `--mic` mutually exclusive on the existing `query` command.

**Files:**
- Modify: `aside/cli.py` — update `query` subparser
- Test: `tests/test_cli.py`

**Step 1: Write failing tests**

```python
def test_query_mic(self):
    args = self.parser.parse_args(["query", "--mic"])
    assert args.mic

def test_query_text_and_mic_exclusive(self):
    # Should fail if both text and --mic provided
    with pytest.raises(SystemExit):
        self.parser.parse_args(["query", "hello", "--mic"])
```

**Step 2: Update subparser** — make text optional, add `--mic`, add validation in `_cmd_query`

**Step 3: Update `_cmd_query`** — if `--mic`, send `{action: "query", mic: true, conversation_id: ...}` without text

**Step 4: Run tests, commit**

```bash
git add aside/cli.py tests/test_cli.py
git commit -m "feat: add --mic flag to query command"
```

---

### Task 7: Remove cost tracking

Remove TOKEN_PRICES, cost calculation, cost from UsageLog and StatusState.

**Files:**
- Modify: `aside/query.py` — remove `TOKEN_PRICES`, `_compute_cost()`, cost from usage logging
- Modify: `aside/state.py` — remove `cost_usd` from `UsageLog.log()`, remove `month_cost()`, update `StatusState`
- Test: `tests/test_query.py`, `tests/test_state.py` — update/remove cost-related tests

**Step 1: Update tests first**

Remove or update any tests that assert on cost values. Update `UsageLog` tests to not include `cost_usd`. Update `StatusState` tests to not include cost in usage dict.

**Step 2: Run tests, verify they fail**

**Step 3: Remove `TOKEN_PRICES` dict and `_compute_cost()` from `query.py`**

**Step 4: Update `UsageLog.log()` in `state.py`** — remove `cost_usd` parameter and field

**Step 5: Update `StatusState.update_usage()`** — remove `query_cost` param, remove `month_cost` and `last_query_cost` from status dict. Keep `total_tokens`.

**Step 6: Update `send_query()` call to `usage_log.log()` and `status.update_usage()`** to remove cost args

**Step 7: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: PASS

**Step 8: Commit**

```bash
git add aside/query.py aside/state.py tests/test_query.py tests/test_state.py
git commit -m "refactor: remove cost tracking, keep token counts"
```

---

### Task 8: Remove action notifications

Remove `notify_final()` and `notify()` progress notifications. Keep error-only notification helper.

**Files:**
- Modify: `aside/query.py` — remove `notify()`, `notify_final()`, add `notify_error()`. Remove notify calls from `send_query()`.
- Modify: `aside/config.py` — remove `reply_command`, `listen_command` from `DEFAULT_CONFIG["notifications"]`
- Test: `tests/test_query.py` — remove notification tests, add `notify_error` test

**Step 1: Write `notify_error()` test**

```python
def test_notify_error_calls_notify_send(self, monkeypatch):
    import subprocess
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append(args))
    from aside.query import notify_error
    notify_error("API key missing")
    assert any("API key missing" in str(c) for c in calls)
```

**Step 2: Run test, verify fail**

**Step 3: Implement `notify_error()`**

```python
def notify_error(message):
    """Send error notification (non-blocking)."""
    try:
        subprocess.Popen(
            ["notify-send", "-a", "Aside", "-u", "critical", "Aside Error", message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass
```

**Step 4: Remove `notify()` and `notify_final()` functions**

**Step 5: Remove all `notify()` and `notify_final()` calls from `send_query()`**

The streaming progress notifications and the final notification call at the end of `send_query()` are removed.

**Step 6: Remove `reply_command` and `listen_command` from config defaults**

Remove the `"notifications"` section from `DEFAULT_CONFIG` entirely, or keep it empty for future use.

**Step 7: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: PASS

**Step 8: Commit**

```bash
git add aside/query.py aside/config.py tests/test_query.py
git commit -m "refactor: remove action notifications, keep error-only"
```

---

### Task 9: Remove wake-word listener

Remove persistent VoiceListener, keep one-shot voice capture as standalone function.

**Files:**
- Modify: `aside/voice/listener.py` — extract `capture_one_shot()` function, remove `VoiceListener` class and `run_wake_word_loop()`
- Modify: `aside/daemon.py` — remove voice listener startup, remove `listen`/`mute`/`unmute`/`toggle-mute` handlers. Add `mic: true` handling in query action.
- Modify: `aside/config.py` — simplify voice config (remove wake_word settings)
- Test: `tests/test_voice.py` — rewrite for one-shot capture
- Test: `tests/test_daemon.py` — remove voice listener tests

**Step 1: Write test for `capture_one_shot()`**

```python
def test_capture_one_shot_returns_text(monkeypatch):
    """One-shot capture: record until silence, transcribe, return text."""
    from aside.voice.listener import capture_one_shot
    # Mock audio recording and STT transcription
    # ... verify returns transcribed string
```

**Step 2: Extract `capture_one_shot()` from existing `_capture_and_send()`**

The core logic is in `_capture_and_send()` (lines 227-359 of `voice/listener.py`). Extract the VAD + recording + transcription into a standalone function that returns text (instead of calling a callback).

```python
def capture_one_shot(config) -> str:
    """Record until silence, transcribe, return text."""
    # VAD loop (from _capture_and_send)
    # STT transcription
    # Return text
```

**Step 3: Remove `VoiceListener` class and `run_wake_word_loop()`**

**Step 4: Update daemon.py**

- Remove voice listener thread startup from `Daemon.run()`
- Remove `listen`, `mute`, `unmute`, `toggle-mute` handlers from `handle_client()`
- In the `query` action handler, if `msg.get("mic")` is True, call `capture_one_shot()` to get text, then proceed with query

**Step 5: Update config defaults** — remove `wake_word_model`, `wake_word_threshold`

**Step 6: Run full test suite**

Run: `python -m pytest tests/ -x -q`

**Step 7: Commit**

```bash
git add aside/voice/ aside/daemon.py aside/config.py tests/test_voice.py tests/test_daemon.py
git commit -m "refactor: remove wake-word listener, add one-shot voice capture"
```

---

### Task 10: Overlay conv_id awareness

Daemon sends `conv_id` in the `open` command. Overlay stores it for use in reply actions.

**Files:**
- Modify: `aside/query.py` — include `conv_id` in the `open` command sent to overlay
- Modify: `overlay/src/socket.c` — parse `conv_id` from `open` command
- Modify: `overlay/src/socket.h` — add `conv_id` field to `overlay_command` struct
- Modify: `overlay/src/main.c` — store `conv_id` in a local variable when CMD_OPEN received

**Step 1: Update Python side**

In `aside/query.py`, where `_overlay_send(sock, {"cmd": "open"})` is called, change to:

```python
_overlay_send(sock, {"cmd": "open", "conv_id": conv["id"]})
```

**Step 2: Update C overlay structs**

In `socket.h`, add to `overlay_command`:

```c
struct overlay_command {
    enum overlay_cmd cmd;
    char data[4096];
    char conv_id[64];  // NEW
};
```

**Step 3: Update `parse_command()` in `socket.c`**

After parsing `cmd` and `data`, also extract `conv_id`:

```c
struct json_object *jid;
if (json_object_object_get_ex(jobj, "conv_id", &jid))
    snprintf(out->conv_id, sizeof(out->conv_id), "%s", json_object_get_string(jid));
else
    out->conv_id[0] = '\0';
```

**Step 4: Store in main.c**

Add a local `char current_conv_id[64] = "";` in main. On CMD_OPEN:

```c
case CMD_OPEN:
    strncpy(current_conv_id, cmd.conv_id, sizeof(current_conv_id) - 1);
    // ... existing open logic
```

**Step 5: Test in VM**

Push, pull in VM, rebuild overlay, restart services. Send a query, check overlay log for any errors.

**Step 6: Commit**

```bash
git add aside/query.py overlay/src/socket.c overlay/src/socket.h overlay/src/main.c
git commit -m "feat: send conv_id from daemon to overlay in open command"
```

---

### Task 11: Overlay action buttons

Render three buttons after CMD_DONE. Handle click events.

**Files:**
- Modify: `overlay/src/main.c` — button state, hit testing, click handlers
- Modify: `overlay/src/render.c` — button rendering function
- Modify: `overlay/src/render.h` — button render declarations

**Step 1: Define button state in main.c**

```c
enum overlay_button { BTN_MIC = 0, BTN_OPEN, BTN_REPLY, BTN_COUNT };

struct button_rect {
    int x, y, w, h;
};

static bool show_buttons = false;
static struct button_rect buttons[BTN_COUNT];
```

**Step 2: Set `show_buttons = true` on CMD_DONE**

In the CMD_DONE handler, set `show_buttons = true`.

On CMD_OPEN and CMD_CLEAR, set `show_buttons = false`.

**Step 3: Add button rendering in render.c**

```c
void renderer_draw_buttons(struct renderer *r, struct overlay_config *cfg,
                           uint32_t *pixels, int width, int height,
                           struct button_rect *rects, int count);
```

Draw three small rounded rects at the bottom of the overlay. Use Pango to render Unicode glyphs or simple text labels ("mic", "open", "reply").

**Step 4: Call button renderer from main.c redraw path**

When `show_buttons && surface_visible`, call `renderer_draw_buttons()` after `renderer_draw()`. Position buttons at bottom of overlay content area.

**Step 5: Add button hit testing in pointer handler**

In the pointer click handler (currently lines 243-285 of main.c), before the existing left-click dismiss:

```c
if (show_buttons && pending_button == BTN_LEFT) {
    for (int i = 0; i < BTN_COUNT; i++) {
        if (pointer_x >= buttons[i].x && pointer_x <= buttons[i].x + buttons[i].w &&
            pointer_y >= buttons[i].y && pointer_y <= buttons[i].y + buttons[i].h) {
            handle_button_click(i);
            pending_button = 0;
            break;
        }
    }
}
```

**Step 6: Implement `handle_button_click()`**

```c
static void handle_button_click(enum overlay_button btn) {
    switch (btn) {
    case BTN_MIC:
        // Send {action: "query", conversation_id: current_conv_id, mic: true} to daemon
        send_to_daemon("{\"action\":\"query\",\"conversation_id\":\"%s\",\"mic\":true}",
                       current_conv_id);
        break;
    case BTN_OPEN:
        // Fork+exec: aside open <conv_id>
        if (fork() == 0) {
            execlp("aside", "aside", "open", current_conv_id, NULL);
            _exit(1);
        }
        break;
    case BTN_REPLY:
        // Enter text input mode (Task 12)
        enter_input_mode();
        break;
    }
}
```

**Step 7: Add `send_to_daemon()` helper**

The overlay already has code to send cancel/stop_tts to the daemon (main.c, lines 243-285). Extract into a reusable function that connects to `aside.sock` and sends JSON.

**Step 8: Test in VM**

Push, pull, rebuild overlay, restart. Send a query, wait for done, verify buttons render. Click each one.

**Step 9: Commit**

```bash
git add overlay/src/main.c overlay/src/render.c overlay/src/render.h
git commit -m "feat: add action buttons to overlay after CMD_DONE"
```

---

### Task 12: Overlay text input

Built-in text input box using wl_keyboard.

**Files:**
- Modify: `overlay/src/main.c` — input mode state, keyboard event handling, submit/escape
- Modify: `overlay/src/render.c` — input box rendering
- Modify: `overlay/src/wayland.h` — add keyboard fields to overlay_state
- Create: `overlay/src/input.c` and `overlay/src/input.h` — text buffer and keyboard handling
- Modify: `overlay/meson.build` — add input.c to sources

**Step 1: Create input state module**

`overlay/src/input.h`:

```c
#ifndef INPUT_H
#define INPUT_H

#include <stdbool.h>
#include <xkbcommon/xkbcommon.h>

struct input_state {
    bool active;
    char text[4096];
    size_t len;
    size_t cursor;

    struct xkb_context *xkb_ctx;
    struct xkb_keymap *xkb_keymap;
    struct xkb_state *xkb_state;
};

void input_init(struct input_state *inp);
void input_cleanup(struct input_state *inp);
void input_activate(struct input_state *inp);
void input_deactivate(struct input_state *inp);
bool input_handle_key(struct input_state *inp, uint32_t key, uint32_t state);
/* Returns true if Enter was pressed (submit). Check inp->text for content.
   Returns false normally. Sets inp->active = false on Escape. */

#endif
```

**Step 2: Implement input.c**

```c
#include "input.h"
#include <string.h>

void input_init(struct input_state *inp) {
    memset(inp, 0, sizeof(*inp));
    inp->xkb_ctx = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
}

void input_activate(struct input_state *inp) {
    inp->active = true;
    inp->text[0] = '\0';
    inp->len = 0;
    inp->cursor = 0;
}

void input_deactivate(struct input_state *inp) {
    inp->active = false;
}

bool input_handle_key(struct input_state *inp, uint32_t key, uint32_t key_state) {
    if (key_state != WL_KEYBOARD_KEY_STATE_PRESSED) return false;

    xkb_keysym_t sym = xkb_state_key_get_one_sym(inp->xkb_state, key + 8);

    if (sym == XKB_KEY_Escape) {
        input_deactivate(inp);
        return false;
    }
    if (sym == XKB_KEY_Return || sym == XKB_KEY_KP_Enter) {
        return true;  // Submit
    }
    if (sym == XKB_KEY_BackSpace) {
        if (inp->len > 0) {
            inp->len--;
            inp->text[inp->len] = '\0';
        }
        return false;
    }

    // Printable character
    char buf[8];
    int n = xkb_state_key_get_utf8(inp->xkb_state, key + 8, buf, sizeof(buf));
    if (n > 0 && inp->len + n < sizeof(inp->text) - 1) {
        memcpy(inp->text + inp->len, buf, n);
        inp->len += n;
        inp->text[inp->len] = '\0';
    }
    return false;
}
```

**Step 3: Add wl_keyboard listener to wayland setup**

In the Wayland seat capability handler, bind `wl_keyboard`. Add keyboard event handlers:

```c
static void keyboard_keymap(void *data, struct wl_keyboard *kb,
                            uint32_t format, int fd, uint32_t size) {
    // Map fd, create xkb_keymap and xkb_state from it
}

static void keyboard_key(void *data, struct wl_keyboard *kb,
                          uint32_t serial, uint32_t time,
                          uint32_t key, uint32_t state) {
    if (input.active) {
        bool submit = input_handle_key(&input, key, state);
        if (submit && input.len > 0) {
            send_to_daemon("{\"action\":\"query\",\"text\":\"%s\","
                          "\"conversation_id\":\"%s\"}",
                          input.text, current_conv_id);
            input_deactivate(&input);
            // Dismiss overlay (destroy surface)
        }
        needs_redraw = true;
    }
}
```

Note: the text sent to daemon needs proper JSON escaping for special characters. Write a simple JSON string escape helper.

**Step 4: Add input box rendering**

In `render.c`, add a function to draw the input box:

```c
void renderer_draw_input(struct renderer *r, struct overlay_config *cfg,
                         uint32_t *pixels, int width, int height,
                         const char *text, size_t cursor_pos);
```

Draw a rounded rect at the bottom of the overlay with the input text. Draw a cursor (blinking vertical line or solid).

**Step 5: Integrate into main loop**

When `input.active`:
- Skip button rendering, show input box instead
- Route keyboard events to input handler
- On submit: send query, dismiss overlay
- On escape: deactivate input, show buttons again

**Step 6: Update meson.build**

Add `input.c` to sources, add `xkbcommon` dependency:

```meson
xkbcommon_dep = dependency('xkbcommon')
# Add to deps list and src list
```

**Step 7: Test in VM**

Push, pull, rebuild overlay (need to install `libxkbcommon-dev` or equivalent in VM). Restart overlay. Test: send query, wait for done, click reply button, type text, press Enter. Verify overlay dismisses and new response streams in.

**Step 8: Commit**

```bash
git add overlay/src/input.c overlay/src/input.h overlay/src/main.c overlay/src/render.c overlay/src/render.h overlay/src/wayland.h overlay/meson.build
git commit -m "feat: add built-in text input to overlay"
```

---

### Task 13: Daemon handles `mic: true` in query action

When the daemon receives a query with `mic: true`, it does one-shot voice capture before processing.

**Files:**
- Modify: `aside/daemon.py` — handle `mic` flag in query action
- Test: `tests/test_daemon.py`

**Step 1: Write failing test**

```python
def test_query_with_mic_calls_capture(monkeypatch):
    """Daemon calls capture_one_shot when mic=True in query."""
    # Mock capture_one_shot to return "test transcription"
    # Send {action: "query", mic: true, conversation_id: "abc"}
    # Verify start_query called with text="test transcription"
```

**Step 2: Update `handle_client()` in daemon.py**

In the query action handler, check for `mic`:

```python
if msg.get("mic"):
    from aside.voice.listener import capture_one_shot
    text = capture_one_shot(self.config.get("voice", {}))
    if not text:
        return  # No speech detected
else:
    text = msg.get("text", "")
```

**Step 3: Run tests, commit**

```bash
git add aside/daemon.py tests/test_daemon.py
git commit -m "feat: daemon handles mic flag for one-shot voice capture"
```

---

### Task 14: Integration testing in VM

End-to-end testing of all changes in the running VM.

**Step 1: Push all changes**

```bash
cd ~/projects/aside && git push
```

**Step 2: Pull and rebuild in VM**

```bash
vmt ssh arch-sway -- "cd /tmp/aside && git pull"
vmt ssh arch-sway -- "cd /tmp/aside/overlay && ninja -C build && sudo ninja -C build install"
vmt ssh arch-sway -- "pip install /tmp/aside --break-system-packages -q"
```

**Step 3: Restart services**

Kill and restart daemon and overlay with correct env vars and Wayland display.

**Step 4: Test CLI commands**

```bash
vmt ssh arch-sway -- "aside ls"
vmt ssh arch-sway -- "aside query 'Hello'"
# Wait for response
vmt ssh arch-sway -- "aside ls"  # Should show conversation
vmt ssh arch-sway -- "aside show <id>"
vmt ssh arch-sway -- "aside reply <id> 'Follow up'"
vmt ssh arch-sway -- "aside rm <id>"
```

**Step 5: Test overlay buttons**

Open SPICE viewer. Send a query. Wait for done. Verify three buttons appear. Click each one:
- Reply: verify input box appears, type text, press Enter, verify overlay dismisses and new response streams
- Open: verify xdg-open launches with markdown file
- Mic: verify voice capture starts (need audio input in VM — may need to skip or mock)

**Step 6: Test notification removal**

Verify no notification popups appear during normal query flow. Verify error notifications still work (e.g., stop daemon, try query from CLI).

**Step 7: Screenshot and verify**

Take screenshots at each stage to confirm visual correctness.
