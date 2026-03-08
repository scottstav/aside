# GTK4 Overlay Port Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the C overlay + aside-input + aside-reply with a single Python/GTK4 overlay process.

**Architecture:** One Adw.Application with a single Gtk.Window using gtk4-layer-shell. A Gtk.Stack switches between stream, conversation, and picker views. Components (AccentBar, MessageView, ReplyInput, ConversationHistory, ConversationPicker) are reusable across views. The overlay listens on `aside-overlay.sock` for commands from the daemon.

**Tech Stack:** Python 3.11+, GTK4 (gi.repository), libadwaita, gtk4-layer-shell, mistune (markdown), Cairo (accent bar animations)

**Design doc:** `docs/plans/2026-03-08-gtk4-overlay-port-design.md`

---

### Task 1: CSS Builder (`aside/overlay/css.py`)

**Files:**
- Create: `aside/overlay/__init__.py`
- Create: `aside/overlay/css.py`
- Test: `tests/test_overlay_css.py`

**Step 1: Write the failing test**

```python
# tests/test_overlay_css.py
"""Tests for aside.overlay.css — CSS generation from config colors."""

from aside.overlay.css import build_css, rgb_strip_alpha


class TestRgbStripAlpha:
    def test_nine_char_hex_strips_alpha(self):
        assert rgb_strip_alpha("#1a1b26e6") == "#1a1b26"

    def test_seven_char_hex_unchanged(self):
        assert rgb_strip_alpha("#1a1b26") == "#1a1b26"


class TestBuildCss:
    def test_returns_string(self):
        css = build_css({
            "background": "#1a1b26e6",
            "foreground": "#c0caf5ff",
            "border": "#414868ff",
            "accent": "#7aa2f7ff",
        })
        assert isinstance(css, str)
        assert "background-color" in css

    def test_uses_default_colors_when_empty(self):
        css = build_css({})
        assert isinstance(css, str)
        assert "background-color" in css

    def test_contains_overlay_classes(self):
        css = build_css({
            "background": "#1a1b26e6",
            "foreground": "#c0caf5ff",
            "border": "#414868ff",
            "accent": "#7aa2f7ff",
        })
        assert ".message-view" in css
        assert ".reply-input" in css
        assert ".accent-bar" in css
        assert ".picker" in css
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_css.py -x -q`
Expected: FAIL — module not found

**Step 3: Write the implementation**

Create `aside/overlay/__init__.py` (empty).

Create `aside/overlay/css.py`:
- `rgb_strip_alpha(color: str) -> str` — strip alpha channel from `#RRGGBBAA` to `#RRGGBB`
- `build_css(colors: dict, font: str = "") -> str` — generate CSS string for all overlay components

CSS should define styles for: `.overlay-container`, `.accent-bar`, `.message-view`, `.message-user`, `.message-llm`, `.reply-input`, `.reply-input:focus`, `.picker`, `.picker-row`, `.picker-row:selected`, `.input-hint`, `.action-bar`.

Use the same pattern from `aside/input/window.py:_build_css()` — take colors dict with `background`, `foreground`, `border`, `accent` keys, apply alpha compositing via GTK's `alpha()` function.

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_css.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/overlay/__init__.py aside/overlay/css.py tests/test_overlay_css.py
git commit -m "feat(overlay): add CSS builder module"
```

---

### Task 2: Markdown Renderer (`aside/overlay/markdown.py`)

**Files:**
- Create: `aside/overlay/markdown.py`
- Test: `tests/test_overlay_markdown.py`

**Step 1: Write the failing test**

```python
# tests/test_overlay_markdown.py
"""Tests for aside.overlay.markdown — markdown to TextBuffer+TextTags."""

import gi
gi.require_version("Gtk", "4.0")

import pytest

try:
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.markdown import render_to_buffer


class TestRenderToBuffer:
    def _make_buffer(self):
        buf = Gtk.TextBuffer()
        return buf

    def test_plain_text(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "Hello world")
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert text == "Hello world"

    def test_bold(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "Hello **bold** world")
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert "bold" in text
        # Verify bold tag exists
        tag_table = buf.get_tag_table()
        assert tag_table.lookup("bold") is not None

    def test_code_span(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "Use `foo()` here")
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert "foo()" in text
        tag_table = buf.get_tag_table()
        assert tag_table.lookup("code") is not None

    def test_code_block(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "```python\nprint('hi')\n```")
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert "print('hi')" in text
        tag_table = buf.get_tag_table()
        assert tag_table.lookup("code-block") is not None

    def test_heading(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "# Title\nBody text")
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert "Title" in text

    def test_disabled_returns_plain(self):
        buf = self._make_buffer()
        render_to_buffer(buf, "**bold** `code`", enabled=False)
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert text == "**bold** `code`"
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_markdown.py -x -q`
Expected: FAIL — module not found

**Step 3: Write the implementation**

Create `aside/overlay/markdown.py`:
- `render_to_buffer(buf: Gtk.TextBuffer, text: str, enabled: bool = True) -> None`
- When `enabled=False`, do `buf.set_text(text, -1)` and return.
- When `enabled=True`:
  1. Parse `text` with `mistune.create_markdown(renderer=None)` to get AST
  2. Walk the AST, insert text into buffer, apply TextTags for each element
  3. Create tags on first use: `bold` (weight=Pango.Weight.BOLD), `italic` (style=Pango.Style.ITALIC), `code` (family="monospace", background), `code-block` (family="monospace", background, paragraph-background), `h1`/`h2`/`h3` (scaled sizes), `list-item` (left-margin indent)
- Tags should be created with `buf.create_tag(name, **props)` if not already in the tag table.

**Reference:** Use `mistune.create_markdown(renderer=None)` which returns an AST (list of dicts). Each dict has `type` and `children`/`raw`/`text` keys. Walk recursively.

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_markdown.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/overlay/markdown.py tests/test_overlay_markdown.py
git commit -m "feat(overlay): add markdown renderer (mistune → TextBuffer+TextTags)"
```

---

### Task 3: AccentBar Widget (`aside/overlay/accent_bar.py`)

**Files:**
- Create: `aside/overlay/accent_bar.py`
- Test: `tests/test_overlay_accent_bar.py`

**Step 1: Write the failing test**

```python
# tests/test_overlay_accent_bar.py
"""Tests for aside.overlay.accent_bar — animated status bar widget."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.accent_bar import AccentBar, BarState


class TestAccentBar:
    def test_initial_state_is_idle(self):
        bar = AccentBar(accent_color="#7aa2f7")
        assert bar.state == BarState.IDLE

    def test_set_state_thinking(self):
        bar = AccentBar(accent_color="#7aa2f7")
        bar.set_state(BarState.THINKING)
        assert bar.state == BarState.THINKING

    def test_set_state_listening(self):
        bar = AccentBar(accent_color="#7aa2f7")
        bar.set_state(BarState.LISTENING)
        assert bar.state == BarState.LISTENING

    def test_set_state_streaming(self):
        bar = AccentBar(accent_color="#7aa2f7")
        bar.set_state(BarState.STREAMING)
        assert bar.state == BarState.STREAMING

    def test_set_state_done(self):
        bar = AccentBar(accent_color="#7aa2f7")
        bar.set_state(BarState.DONE)
        assert bar.state == BarState.DONE

    def test_height_request(self):
        bar = AccentBar(accent_color="#7aa2f7", height=4)
        min_h = bar.get_size_request()[1]
        assert min_h == 4
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_accent_bar.py -x -q`
Expected: FAIL — module not found

**Step 3: Write the implementation**

Create `aside/overlay/accent_bar.py`:
- `BarState` — enum: `IDLE`, `THINKING`, `LISTENING`, `STREAMING`, `DONE`
- `AccentBar(Gtk.DrawingArea)`:
  - `__init__(self, accent_color: str, height: int = 3)` — parse color, set size request to `(-1, height)`, connect `draw` signal via `set_draw_func(self._draw)`
  - `state` property
  - `set_state(self, state: BarState)` — update state, start/stop tick callback for animations
  - `_draw(self, area, cr, width, height)` — Cairo drawing:
    - IDLE: solid bar in accent color
    - THINKING: sweep animation (bright spot moves left-to-right)
    - LISTENING: breathing/pulse (bar opacity oscillates)
    - STREAMING: subtle shimmer (thin bright line sweeps)
    - DONE: fade out (opacity decreasing to 0)
  - `_on_tick(self, widget, frame_clock)` — advance animation progress based on frame time, call `queue_draw()`, return `True` to keep ticking or `False` for DONE

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_accent_bar.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/overlay/accent_bar.py tests/test_overlay_accent_bar.py
git commit -m "feat(overlay): add AccentBar widget with animated states"
```

---

### Task 4: MessageView Widget (`aside/overlay/message_view.py`)

**Files:**
- Create: `aside/overlay/message_view.py`
- Test: `tests/test_overlay_message_view.py`

**Step 1: Write the failing test**

```python
# tests/test_overlay_message_view.py
"""Tests for aside.overlay.message_view — single message display widget."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.message_view import MessageView


class TestMessageView:
    def test_create_llm_message(self):
        mv = MessageView(role="assistant", text="Hello", markdown=True)
        assert mv.role == "assistant"

    def test_create_user_message(self):
        mv = MessageView(role="user", text="Hi there", markdown=True)
        assert mv.role == "user"

    def test_append_text(self):
        mv = MessageView(role="assistant", text="Hello", markdown=True)
        mv.set_text("Hello world")
        buf = mv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert "world" in text

    def test_get_text(self):
        mv = MessageView(role="assistant", text="Test content", markdown=True)
        assert mv.get_raw_text() == "Test content"

    def test_plain_text_mode(self):
        mv = MessageView(role="assistant", text="**bold**", markdown=False)
        buf = mv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        assert text == "**bold**"
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_message_view.py -x -q`
Expected: FAIL — module not found

**Step 3: Write the implementation**

Create `aside/overlay/message_view.py`:
- `MessageView(Gtk.Box)`:
  - `__init__(self, role: str, text: str = "", markdown: bool = True)` — vertical box containing a `Gtk.ScrolledWindow` with a `Gtk.TextView` (read-only, non-editable, word-wrap)
  - `role` property — `"user"` or `"assistant"`
  - CSS class: `.message-view` + `.message-user` or `.message-llm` based on role
  - `_raw_text: str` — stores the raw markdown source
  - `set_text(self, text: str)` — update `_raw_text`, re-render via `markdown.render_to_buffer()`
  - `get_raw_text(self) -> str` — return `_raw_text`
  - `get_buffer(self) -> Gtk.TextBuffer` — return the underlying buffer
  - TextView should be non-editable, cursor-visible=False, wrap-mode=WORD_CHAR

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_message_view.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/overlay/message_view.py tests/test_overlay_message_view.py
git commit -m "feat(overlay): add MessageView widget with markdown support"
```

---

### Task 5: ReplyInput Widget (`aside/overlay/reply_input.py`)

**Files:**
- Create: `aside/overlay/reply_input.py`
- Test: `tests/test_overlay_reply_input.py`

**Step 1: Write the failing test**

```python
# tests/test_overlay_reply_input.py
"""Tests for aside.overlay.reply_input — text entry widget."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.reply_input import ReplyInput


class TestReplyInput:
    def test_create(self):
        ri = ReplyInput()
        assert isinstance(ri, Gtk.Box)

    def test_get_text_empty(self):
        ri = ReplyInput()
        assert ri.get_text() == ""

    def test_clear(self):
        ri = ReplyInput()
        ri.clear()
        assert ri.get_text() == ""

    def test_has_css_class(self):
        ri = ReplyInput()
        assert ri.has_css_class("reply-input-container")
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_reply_input.py -x -q`
Expected: FAIL — module not found

**Step 3: Write the implementation**

Create `aside/overlay/reply_input.py`:
- `ReplyInput(Gtk.Box)`:
  - `__init__(self)` — vertical box with CSS class `reply-input-container`
  - Contains: `Gtk.ScrolledWindow` (min-height 32, max-height 160, propagate natural height) with an editable `Gtk.TextView` (word-wrap, CSS class `reply-input`)
  - Hint label: "Enter to send • Shift+Enter for newline • Esc to close" (CSS class `input-hint`)
  - `get_text(self) -> str` — return stripped text from the buffer
  - `clear(self)` — clear the text buffer
  - `connect_submit(self, callback: Callable[[str], None])` — register a callback for Enter key. Internally adds `EventControllerKey` that calls `callback(text)` on Enter (not Shift+Enter)
  - `focus_input(self)` — call `grab_focus()` on the textview

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_reply_input.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/overlay/reply_input.py tests/test_overlay_reply_input.py
git commit -m "feat(overlay): add ReplyInput widget"
```

---

### Task 6: ConversationHistory Widget (`aside/overlay/conversation.py`)

**Files:**
- Create: `aside/overlay/conversation.py`
- Test: `tests/test_overlay_conversation.py`

**Step 1: Write the failing test**

```python
# tests/test_overlay_conversation.py
"""Tests for aside.overlay.conversation — scrollable message history."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.conversation import ConversationHistory


class TestConversationHistory:
    def test_create_empty(self):
        ch = ConversationHistory(markdown=True)
        assert ch.message_count() == 0

    def test_add_message(self):
        ch = ConversationHistory(markdown=True)
        ch.add_message("assistant", "Hello")
        assert ch.message_count() == 1

    def test_add_multiple_messages(self):
        ch = ConversationHistory(markdown=True)
        ch.add_message("user", "Hi")
        ch.add_message("assistant", "Hello!")
        assert ch.message_count() == 2

    def test_clear(self):
        ch = ConversationHistory(markdown=True)
        ch.add_message("assistant", "Hello")
        ch.clear()
        assert ch.message_count() == 0

    def test_load_conversation(self):
        conv = {
            "id": "test-123",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ]
        }
        ch = ConversationHistory(markdown=True)
        ch.load_conversation(conv)
        assert ch.message_count() == 2

    def test_update_last_message(self):
        ch = ConversationHistory(markdown=True)
        ch.add_message("assistant", "Hello")
        ch.update_last_message("Hello world")
        last = ch.get_last_message()
        assert last.get_raw_text() == "Hello world"
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_conversation.py -x -q`
Expected: FAIL — module not found

**Step 3: Write the implementation**

Create `aside/overlay/conversation.py`:
- `ConversationHistory(Gtk.ScrolledWindow)`:
  - `__init__(self, markdown: bool = True)` — scrolled window containing a vertical `Gtk.Box` that holds `MessageView` widgets
  - `_messages: list[MessageView]` — ordered list of message widgets
  - `_markdown: bool`
  - `add_message(self, role: str, text: str) -> MessageView` — create a `MessageView`, append to the box and the list, scroll to bottom
  - `update_last_message(self, text: str)` — update the last `MessageView`'s text (for streaming)
  - `get_last_message(self) -> MessageView | None`
  - `message_count(self) -> int`
  - `clear(self)` — remove all children and clear the list
  - `load_conversation(self, conv: dict)` — clear and populate from a conversation dict (iterate `conv["messages"]`, skip tool messages, extract text from user content including multimodal)
  - Auto-scroll: when new content is added, scroll to bottom (use `Gtk.Adjustment` on the vadjustment)

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_conversation.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/overlay/conversation.py tests/test_overlay_conversation.py
git commit -m "feat(overlay): add ConversationHistory widget"
```

---

### Task 7: ConversationPicker Widget (`aside/overlay/picker.py`)

**Files:**
- Create: `aside/overlay/picker.py`
- Test: `tests/test_overlay_picker.py`

**Step 1: Write the failing test**

```python
# tests/test_overlay_picker.py
"""Tests for aside.overlay.picker — conversation list selector."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.picker import ConversationPicker


class TestConversationPicker:
    def test_create(self):
        picker = ConversationPicker()
        assert isinstance(picker, Gtk.Box)

    def test_populate(self):
        entries = [
            ("id-1", "2026-03-08T12:00:00+00:00", "First conversation"),
            ("id-2", "2026-03-07T10:00:00+00:00", "Second conversation"),
        ]
        picker = ConversationPicker()
        picker.populate(entries)
        # Should have 3 rows: "New conversation" + 2 entries
        assert picker.row_count() == 3

    def test_new_conversation_is_first(self):
        picker = ConversationPicker()
        picker.populate([])
        assert picker.get_selected_id() == "__new__"

    def test_has_text_input(self):
        picker = ConversationPicker()
        assert picker.get_text() == ""
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_picker.py -x -q`
Expected: FAIL — module not found

**Step 3: Write the implementation**

Create `aside/overlay/picker.py`:
- `ConversationPicker(Gtk.Box)`:
  - `__init__(self)` — vertical box with CSS class `picker`. Contains:
    - Title label "aside" (CSS class `picker-title`)
    - `Gtk.ScrolledWindow` with `Gtk.ListBox` (CSS class `picker-listbox`)
    - `Gtk.ScrolledWindow` with editable `Gtk.TextView` for query input (CSS class `picker-input`)
    - Hint label
  - `populate(self, entries: list[tuple[str, str, str]])` — clear listbox, add "New conversation" row first, then one row per entry (same row format as current `aside/input/window.py:_make_conversation_row`)
  - `get_selected_id(self) -> str` — return selected conversation ID (`"__new__"` for new)
  - `get_text(self) -> str` — return text from the input TextView
  - `row_count(self) -> int`
  - `connect_submit(self, callback: Callable[[str, str], None])` — callback receives `(text, conversation_id)`
  - Keyboard handling: Ctrl+N/P navigate list, Tab focuses input, Enter submits, Escape emits close signal

Port the existing row-building logic from `aside/input/window.py:_make_conversation_row` and `_make_new_conversation_row`.

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_picker.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/overlay/picker.py tests/test_overlay_picker.py
git commit -m "feat(overlay): add ConversationPicker widget"
```

---

### Task 8: Main Window & State Machine (`aside/overlay/window.py`)

**Files:**
- Create: `aside/overlay/window.py`
- Test: `tests/test_overlay_window.py`

**Step 1: Write the failing test**

```python
# tests/test_overlay_window.py
"""Tests for aside.overlay.window — main window and state machine."""

import pytest

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    HAS_GTK = True
except (ImportError, ValueError):
    HAS_GTK = False

pytestmark = pytest.mark.skipif(not HAS_GTK, reason="GTK4 not available")

from aside.overlay.window import OverlayState


class TestOverlayState:
    """Test the state enum values exist."""
    def test_states_exist(self):
        assert OverlayState.HIDDEN is not None
        assert OverlayState.STREAMING is not None
        assert OverlayState.DISPLAY is not None
        assert OverlayState.REPLY is not None
        assert OverlayState.CONVO is not None
        assert OverlayState.PICKER is not None
```

Note: Full window tests require a Wayland display and layer-shell, so unit tests are limited to the state enum and pure logic. Integration testing happens in the VM.

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_window.py -x -q`
Expected: FAIL — module not found

**Step 3: Write the implementation**

Create `aside/overlay/window.py`:
- `OverlayState` — enum: `HIDDEN`, `STREAMING`, `DISPLAY`, `REPLY`, `CONVO`, `PICKER`
- `OverlayWindow(Gtk.Window)`:
  - `__init__(self, app: Adw.Application, config: dict)`:
    - Load config values (position, margins, width, colors, font, markdown toggle)
    - Set up gtk4-layer-shell (OVERLAY layer, ON_DEMAND keyboard, configurable anchoring)
    - Build widget tree:
      - `Gtk.Box` (vertical)
        - `AccentBar` (from config accent color)
        - `Gtk.Stack` with transition type CROSSFADE
          - `"stream"` page: `Gtk.Box` with `ConversationHistory` (for single message) + action button bar
          - `"convo"` page: `Gtk.Box` with `ConversationHistory` (for full history) + `ReplyInput`
          - `"picker"` page: `ConversationPicker`
    - Apply CSS via `css.build_css()`
    - Set initial state to HIDDEN, window invisible
  - `_state: OverlayState` property
  - `_conv_id: str | None` — current conversation ID
  - State transition methods (called by socket handler):
    - `handle_open(self, mode: str, conv_id: str = "")` — HIDDEN→STREAMING: show window, clear stream view, add empty assistant MessageView, set AccentBar to STREAMING
    - `handle_text(self, data: str)` — append to current MessageView's raw text, re-render
    - `handle_done(self)` — STREAMING→DISPLAY: set AccentBar to IDLE, show action buttons
    - `handle_clear(self)` — any→HIDDEN: hide window
    - `handle_replace(self, data: str)` — replace text in current MessageView
    - `handle_thinking(self)` — set AccentBar to THINKING
    - `handle_listening(self)` — set AccentBar to LISTENING
    - `handle_input(self)` — any→PICKER: populate picker from ConversationStore, switch stack, show window
    - `handle_reply(self, conv_id: str)` — any→CONVO: load conversation, show history + reply input
    - `handle_convo(self, conv_id: str)` — any→CONVO: load conversation, show history (no reply focus)
  - User action handlers:
    - Reply button click → DISPLAY→REPLY: show ReplyInput below stream view, grab keyboard
    - Shift+Tab in reply → REPLY→CONVO: populate full history, switch stack page
    - Submit in ReplyInput → send `{"action":"query", "text":"...", "conversation_id":"..."}` to daemon socket, transition to STREAMING (waiting for response)
    - Submit in picker → send query to daemon, transition to STREAMING
    - Escape → HIDDEN
  - Action button bar: Reply (text), Mic (if STT available), Open transcript, Dismiss
  - Keyboard controller for Escape (window-level)

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_window.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/overlay/window.py tests/test_overlay_window.py
git commit -m "feat(overlay): add main window with state machine and view switching"
```

---

### Task 9: Application & Socket Listener (`aside/overlay/app.py`)

**Files:**
- Create: `aside/overlay/app.py`
- Test: `tests/test_overlay_app.py`

**Step 1: Write the failing test**

```python
# tests/test_overlay_app.py
"""Tests for aside.overlay.app — socket command parsing."""

from aside.overlay.app import parse_command


class TestParseCommand:
    def test_open(self):
        cmd = parse_command('{"cmd":"open","mode":"user"}')
        assert cmd == {"cmd": "open", "mode": "user"}

    def test_text(self):
        cmd = parse_command('{"cmd":"text","data":"hello"}')
        assert cmd == {"cmd": "text", "data": "hello"}

    def test_input(self):
        cmd = parse_command('{"cmd":"input"}')
        assert cmd == {"cmd": "input"}

    def test_reply(self):
        cmd = parse_command('{"cmd":"reply","conversation_id":"abc-123"}')
        assert cmd == {"cmd": "reply", "conversation_id": "abc-123"}

    def test_invalid_json_returns_none(self):
        assert parse_command("not json") is None

    def test_empty_returns_none(self):
        assert parse_command("") is None
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_app.py -x -q`
Expected: FAIL — module not found

**Step 3: Write the implementation**

Create `aside/overlay/app.py`:

```python
"""GTK4 overlay application — socket listener + main entry point."""

import ctypes
import json
import logging
import os
import socket
import threading

_LAYER_SHELL_LIB = os.environ.get("GTK4_LAYER_SHELL_LIB", "libgtk4-layer-shell.so")
try:
    ctypes.CDLL(_LAYER_SHELL_LIB, mode=ctypes.RTLD_GLOBAL)
except OSError:
    pass

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Adw, GLib

from aside.config import load_config, resolve_socket_path

log = logging.getLogger(__name__)


def parse_command(line: str) -> dict | None:
    """Parse a JSON command line. Returns None on invalid input."""
    if not line.strip():
        return None
    try:
        return json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None


class OverlayApp(Adw.Application):
    """Main overlay application — manages window and socket listener."""

    def __init__(self) -> None:
        super().__init__(application_id="dev.aside.overlay")
        self._config = load_config()
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)

    def do_activate(self) -> None:
        from aside.overlay.window import OverlayWindow
        self._window = OverlayWindow(self, self._config)
        # Don't present — window starts hidden
        # Start socket listener thread
        threading.Thread(target=self._listen_socket, daemon=True).start()

    def _listen_socket(self) -> None:
        """Listen on aside-overlay.sock for commands from the daemon."""
        sock_path = resolve_socket_path("aside-overlay.sock")
        try:
            os.unlink(str(sock_path))
        except FileNotFoundError:
            pass

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        os.chmod(str(sock_path), 0o600)
        server.listen(5)
        log.info("Overlay listening on %s", sock_path)

        while True:
            conn, _ = server.accept()
            threading.Thread(
                target=self._handle_connection,
                args=(conn,),
                daemon=True,
            ).start()

    def _handle_connection(self, conn: socket.socket) -> None:
        """Read newline-delimited JSON commands from a connection."""
        buf = b""
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    cmd = parse_command(line.decode("utf-8", errors="replace"))
                    if cmd:
                        GLib.idle_add(self._dispatch, cmd)
            # Handle any remaining data without newline
            if buf.strip():
                cmd = parse_command(buf.decode("utf-8", errors="replace"))
                if cmd:
                    GLib.idle_add(self._dispatch, cmd)
        except OSError:
            pass
        finally:
            conn.close()

    def _dispatch(self, cmd: dict) -> bool:
        """Dispatch a command to the overlay window. Runs on GTK main thread."""
        name = cmd.get("cmd", "")
        if name == "open":
            self._window.handle_open(cmd.get("mode", "user"), cmd.get("conv_id", ""))
        elif name == "text":
            self._window.handle_text(cmd.get("data", ""))
        elif name == "done":
            self._window.handle_done()
        elif name == "clear":
            self._window.handle_clear()
        elif name == "replace":
            self._window.handle_replace(cmd.get("data", ""))
        elif name == "thinking":
            self._window.handle_thinking()
        elif name == "listening":
            self._window.handle_listening()
        elif name == "input":
            self._window.handle_input()
        elif name == "reply":
            self._window.handle_reply(cmd.get("conversation_id", ""))
        elif name == "convo":
            self._window.handle_convo(cmd.get("conversation_id", ""))
        return False  # remove from idle queue


def main() -> None:
    """Entry point for aside-overlay."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    app = OverlayApp()
    app.run([])
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_app.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/overlay/app.py tests/test_overlay_app.py
git commit -m "feat(overlay): add application with socket listener and command dispatch"
```

---

### Task 10: Update CLI — Add `input`, `view` Commands; Update `reply`

**Files:**
- Modify: `aside/cli.py`
- Test: `tests/test_cli.py` (add new tests)

**Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestInputCommand:
    """Tests for aside input command."""

    def test_input_sends_to_overlay_socket(self):
        """aside input should send {"cmd":"input"} to overlay socket."""
        # Test that _send_overlay is called with the correct command
        with mock.patch("aside.cli._send_overlay") as mock_send:
            args = argparse.Namespace(command="input")
            _cmd_input(args)
            mock_send.assert_called_once_with({"cmd": "input"})


class TestViewCommand:
    """Tests for aside view command."""

    def test_view_sends_to_overlay_socket(self):
        """aside view <id> should send {"cmd":"convo"} to overlay socket."""
        with mock.patch("aside.cli._send_overlay") as mock_send:
            with mock.patch("aside.cli._resolve_conv_id", return_value="full-uuid"):
                with mock.patch("aside.cli.load_config", return_value=DEFAULT_CONFIG):
                    with mock.patch("aside.cli.resolve_conversations_dir"):
                        args = argparse.Namespace(command="view", conversation_id="abc")
                        _cmd_view(args)
            mock_send.assert_called_once_with({"cmd": "convo", "conversation_id": "full-uuid"})
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -x -q -k "test_input_sends or test_view_sends"`
Expected: FAIL

**Step 3: Implement the changes**

In `aside/cli.py`:

1. Add `_send_overlay(msg: dict)` helper — same as `_send()` but connects to `resolve_socket_path("aside-overlay.sock")`

2. Add `aside input` subcommand:
   ```python
   sub.add_parser("input", help="Open the conversation picker overlay")
   ```
   Handler `_cmd_input`: calls `_send_overlay({"cmd": "input"})`

3. Add `aside view <conversation_id>` subcommand:
   ```python
   view_cmd = sub.add_parser("view", help="View a conversation in the overlay")
   view_cmd.add_argument("conversation_id", help="Conversation ID to view")
   ```
   Handler `_cmd_view`: resolves conv ID prefix, calls `_send_overlay({"cmd": "convo", "conversation_id": full_id})`

4. Update `aside reply` handler:
   - When called with just an ID (no `--text`, no `--mic`, no `--gui`), send `{"cmd": "reply", "conversation_id": full_id}` to the overlay socket instead of prompting for text on stdin
   - Remove `--gui` flag (no longer needed — overlay handles it)
   - Keep `--mic` and text args as-is (those still go to daemon)

5. Add `"input"`, `"view"` to `_HANDLERS` dict

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/cli.py tests/test_cli.py
git commit -m "feat(cli): add input, view commands; update reply to use overlay"
```

---

### Task 11: Update Daemon — Remove overlay.conf, Remove Pipe IPC

**Files:**
- Modify: `aside/daemon.py`
- Modify: `tests/test_daemon.py`

**Step 1: Identify what to remove**

Read `aside/daemon.py` and find:
- `_write_overlay_config()` function (lines ~139-175)
- Its call in `run()` (lines ~507-513)
- Any code that spawns `aside-reply` or `aside-input` processes
- Pipe fd creation for reply window coordination

**Step 2: Write tests for new behavior**

Update `tests/test_daemon.py`:
- Remove `test_overlay_config_maps_color_keys`, `test_overlay_config_custom_values`, `test_overlay_config_creates_parent_dirs` (these test the deleted `_write_overlay_config`)
- Add test: `test_run_does_not_write_overlay_conf` — verify `overlay.conf` is not created

**Step 3: Make the changes**

In `aside/daemon.py`:
- Delete `_write_overlay_config()` function
- Remove the overlay.conf writing from `run()`
- Remove any subprocess.Popen calls for aside-reply/aside-input
- Remove pipe creation code (if any) for reply window coordination
- Where the daemon currently spawns `aside-reply`, instead send `{"cmd":"reply","conversation_id":"..."}` to the overlay socket

**Step 4: Run tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_daemon.py -x -q`
Expected: PASS

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: PASS (full suite)

**Step 5: Commit**

```bash
git add aside/daemon.py tests/test_daemon.py
git commit -m "refactor(daemon): remove overlay.conf generation and pipe IPC"
```

---

### Task 12: Update pyproject.toml and Systemd Service

**Files:**
- Modify: `pyproject.toml`
- Modify: `data/aside-overlay.service`

**Step 1: Update pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "aside-assistant"
version = "0.4.0"  # bump for GTK4 overlay
dependencies = [
    "litellm>=1.30.0",
    "mistune>=3.0",
]

[project.scripts]
aside = "aside.cli:main"
aside-overlay = "aside.overlay.app:main"
aside-status = "aside.status:main"
```

Changes:
- Build system: `meson-python` → `setuptools` (no more C build)
- Add `mistune>=3.0` dependency
- Remove `aside-input` and `aside-reply` entry points
- Add `aside-overlay` entry point
- Bump version to 0.4.0

**Step 2: Update systemd service**

```ini
[Unit]
Description=aside - Wayland overlay
After=graphical-session.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=%h/.local/bin/aside-overlay
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

Essentially unchanged — just points to the new Python `aside-overlay` binary instead of the C one.

**Step 3: Commit**

```bash
git add pyproject.toml data/aside-overlay.service
git commit -m "chore: switch build to setuptools, add mistune, update entry points"
```

---

### Task 13: Update Makefile — Remove C Build, Simplify

**Files:**
- Modify: `Makefile`

**Step 1: Update the Makefile**

Remove:
- `overlay` target (meson/ninja build)
- `overlay` dependency from `dev` and `install`
- `install -m755 $(BUILDDIR)/overlay/aside-overlay` line from `install` and `dev`
- References to `aside-input`, `aside-reply` binary symlinks

Update:
- `dev` target: copy `aside/overlay/*.py` to `$(SITE)/overlay/`, no C binary install
- `install` target: `for cmd` loop should list `aside aside-overlay aside-status`
- `clean` target: remove `overlay/build` references (the directory is being deleted)

**Step 2: Verify**

Run: `make -n install` to dry-run and verify commands look correct

**Step 3: Commit**

```bash
git add Makefile
git commit -m "chore(makefile): remove C build, simplify for pure Python"
```

---

### Task 14: Delete Old Code

**Files:**
- Delete: `overlay/` (entire directory)
- Delete: `aside/input/` (entire directory)
- Delete: `aside/reply/` (entire directory)

**Step 1: Verify no remaining references**

Run: `grep -r "aside/input/" aside/ tests/` and `grep -r "aside/reply/" aside/ tests/` to find any imports or references that need updating.

Run: `grep -r "overlay/build\|overlay/src\|meson.build" aside/ tests/ Makefile` to verify no C overlay references remain.

**Step 2: Delete the directories**

```bash
rm -rf overlay/
rm -rf aside/input/
rm -rf aside/reply/
```

**Step 3: Update any remaining test imports**

In `tests/test_cli.py`: update or remove tests that reference `aside-input` subprocess spawning (the `test_reply_gui` test that asserts `Popen(["aside-input", ...])` should be updated to test the new overlay socket approach).

**Step 4: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add -A  # stages deletions
git commit -m "chore: delete C overlay, input/reply packages (replaced by GTK4 overlay)"
```

---

### Task 15: Add `overlay.markdown` Config Key

**Files:**
- Modify: `aside/config.py`
- Modify: `tests/test_config.py`

**Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_overlay_markdown_default_true(self):
    cfg = load_config()
    assert cfg["overlay"]["markdown"] is True
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_config.py -x -q -k "test_overlay_markdown"`
Expected: FAIL

**Step 3: Add the key**

In `aside/config.py`, add `"markdown": True` to `DEFAULT_CONFIG["overlay"]`.

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_config.py -x -q`
Expected: PASS

**Step 5: Commit**

```bash
git add aside/config.py tests/test_config.py
git commit -m "feat(config): add overlay.markdown toggle (default true)"
```

---

### Task 16: Integration Test — Full Socket Flow

**Files:**
- Create: `tests/test_overlay_integration.py`

**Step 1: Write the test**

```python
# tests/test_overlay_integration.py
"""Integration test — verify socket command dispatch."""

import json
import pytest
from unittest import mock

from aside.overlay.app import parse_command


class TestCommandDispatch:
    """Verify all socket commands parse and map to handler methods."""

    COMMANDS = [
        ('{"cmd":"open","mode":"user"}', "handle_open"),
        ('{"cmd":"text","data":"hello"}', "handle_text"),
        ('{"cmd":"done"}', "handle_done"),
        ('{"cmd":"clear"}', "handle_clear"),
        ('{"cmd":"replace","data":"new text"}', "handle_replace"),
        ('{"cmd":"thinking"}', "handle_thinking"),
        ('{"cmd":"listening"}', "handle_listening"),
        ('{"cmd":"input"}', "handle_input"),
        ('{"cmd":"reply","conversation_id":"abc"}', "handle_reply"),
        ('{"cmd":"convo","conversation_id":"abc"}', "handle_convo"),
    ]

    @pytest.mark.parametrize("json_str,expected_handler", COMMANDS)
    def test_command_parses(self, json_str, expected_handler):
        cmd = parse_command(json_str)
        assert cmd is not None
        assert "cmd" in cmd

    def test_unknown_command_ignored(self):
        cmd = parse_command('{"cmd":"bogus"}')
        assert cmd is not None  # parses OK
        assert cmd["cmd"] == "bogus"  # but no handler will match

    def test_malformed_json(self):
        assert parse_command("{bad json") is None
```

**Step 2: Run test**

Run: `source .venv/bin/activate && python -m pytest tests/test_overlay_integration.py -x -q`
Expected: PASS (since parse_command exists from Task 9)

**Step 3: Commit**

```bash
git add tests/test_overlay_integration.py
git commit -m "test: add integration tests for overlay socket command dispatch"
```

---

### Task 17: Update `dev/vm-sync.sh` and Test in VM

**Files:**
- Modify: `dev/vm-sync.sh`

**Step 1: Update vm-sync.sh**

The script currently builds the C overlay and installs it. Update to:
- Remove meson/ninja build step
- Remove C binary install
- Ensure `pip install .` installs the new `aside-overlay` entry point
- Update service restart: `systemctl --user restart aside-daemon aside-overlay`

**Step 2: Boot VM and test**

```bash
cd ~/projects/vmt && source .venv/bin/activate
vmt up aside-ubuntu-kde
vmt ssh aside-ubuntu-kde -- "cloud-init status --wait"
dev/vm-sync.sh --setup
dev/vm-sync.sh
```

**Step 3: Manual testing in VM**

Open SPICE viewer: `vmt view aside-ubuntu-kde`

Test each flow:
1. `aside query "Hello"` — overlay shows, text streams, accent bar animates, done shows buttons
2. Click Reply → text input appears below response
3. Shift+Tab → conversation expands, history visible
4. Type reply, Enter → sends query, streams new response
5. `aside input` → picker appears, select conversation, Tab → conversation view
6. `aside reply <conv-id>` → conversation view with reply input
7. `aside view <conv-id>` → conversation view (no reply focus)
8. `aside dismiss` → overlay hides
9. Escape from any state → hides

**Step 4: Commit any fixes**

```bash
git add dev/vm-sync.sh
git commit -m "chore(vm): update vm-sync for pure Python overlay"
```

---

### Task 18: Update Install Docs

**Files:**
- Modify: `README.md`

**Step 1: Update build instructions**

Remove:
- meson/ninja as dependencies
- C compiler requirements
- wayland-protocols, cairo, pango dev packages (for building)
- Any reference to `overlay/` build

Add:
- `mistune` is installed automatically via pip
- gtk4-layer-shell is still a runtime dependency (system package)

Update install command to just `pip install .` (no meson involved).

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update install instructions for pure Python build"
```
