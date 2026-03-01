# Reply Box Cleanup & Configurable Colors

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove dead button bar code from the GTK actions window, rename it to "reply", and make its colors use `overlay.colors` from config.

**Architecture:** The GTK reply window is spawned by the C overlay via `execl`. It already imports `load_config()`. We strip the dead button mode, rename `aside/actions/` to `aside/reply/`, and generate CSS at runtime using the user's `overlay.colors` values instead of hardcoded libadwaita theme variables.

**Tech Stack:** Python/GTK4, C, Meson, TOML config

---

### Task 1: Rename `aside/actions/` to `aside/reply/`

**Files:**
- Rename: `aside/actions/` → `aside/reply/`
- Modify: `pyproject.toml:26`
- Modify: `meson.build:25-29`
- Modify: `Makefile:20-24,43,77`
- Modify: `overlay/src/main.c:115-119,132`

**Step 1: Move the directory**

```bash
git mv aside/actions aside/reply
```

**Step 2: Update pyproject.toml entry point**

Change line 26 from:
```
aside-actions = "aside.actions.window:main"
```
to:
```
aside-reply = "aside.reply.window:main"
```

**Step 3: Update meson.build**

Change lines 25-29 from:
```meson
py.install_sources(
  'aside/actions/__init__.py',
  'aside/actions/window.py',
  preserve_path: true,
)
```
to:
```meson
py.install_sources(
  'aside/reply/__init__.py',
  'aside/reply/window.py',
  preserve_path: true,
)
```

**Step 4: Update Makefile — replace `aside-actions` with `aside-reply`**

In the `dev:` target (line 20) and `install:` target (line 43), change `aside-actions` to `aside-reply` in the `for cmd` loop.

In the `uninstall:` target (line 77), change `aside-actions` to `aside-reply` in the `rm` command.

**Step 5: Update C overlay spawn code**

In `overlay/src/main.c`, update `spawn_reply_input()`:

Change line 115:
```c
char bin[512] = "aside-reply";
```

Change line 117:
```c
snprintf(bin, sizeof(bin), "%s/.local/bin/aside-reply", home);
```

Change line 119:
```c
snprintf(bin, sizeof(bin), "aside-reply");
```

Change line 132:
```c
execl(bin, "aside-reply",
```

**Step 6: Run tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -x -q
```

Expected: all 248 tests pass (no tests reference the actions module directly).

**Step 7: Commit**

```bash
git add -A
git commit -m "Rename aside-actions to aside-reply"
```

---

### Task 2: Strip dead button bar code from `aside/reply/window.py`

**Files:**
- Modify: `aside/reply/window.py`

**Step 1: Remove button-mode CSS**

Delete the `.action-bar` and `button.action-btn` CSS rules (lines 57-81 in the original). Keep only:
- `window` transparency rules
- `.input-bar`
- `.reply-input` / `.reply-input:focus`
- `.reply-hint`

**Step 2: Remove button-mode methods and branching**

Remove from `ActionsWindow`:
- `_build_button_mode()` method
- `_on_mic()` method
- `_on_open()` method
- `_on_reply()` method
- All `reply_only` parameter and branching — the window is always reply-only now
- The `Gtk.Stack` — replace with the input vbox directly as the child
- The Escape handler's "go back to buttons" branch — Escape always closes

Remove from `ActionsApp`:
- `reply_only` parameter

Remove from `main()` / `argparse`:
- `--reply` argument

**Step 3: Simplify `__init__`**

The constructor should:
1. Set up layer shell (same as now, minus `reply_only` branches)
2. Set keyboard mode to `ON_DEMAND` always
3. Build the input UI directly (no stack)
4. Set size request to width
5. Grab focus on the textview

**Step 4: Simplified Escape handler**

```python
def _on_key(self, ctl, keyval, keycode, state):
    if keyval == Gdk.KEY_Escape:
        self.close()
        return True
    return False
```

**Step 5: Run tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -x -q
```

**Step 6: Commit**

```bash
git add aside/reply/window.py
git commit -m "Strip dead button bar code from reply window"
```

---

### Task 3: Make reply box use `overlay.colors` from config

**Files:**
- Modify: `aside/reply/window.py`

**Step 1: Add a helper to strip alpha from hex colors**

```python
def _rgb(color: str) -> str:
    """Return '#RRGGBB' from '#RRGGBB' or '#RRGGBBAA'."""
    if len(color) == 9:  # #RRGGBBAA
        return color[:7]
    return color
```

**Step 2: Replace the hardcoded CSS string with a function**

```python
def _build_css(colors: dict) -> str:
    bg = _rgb(colors.get("background", "#1a1b26"))
    fg = _rgb(colors.get("foreground", "#c0caf5"))
    accent = _rgb(colors.get("accent", "#7aa2f7"))
    border = _rgb(colors.get("border", "#414868"))

    return f"""
window {{
    background-color: transparent;
}}
window.background {{
    background-color: transparent;
}}
.input-bar {{
    background-color: alpha({bg}, 0.95);
    border-radius: 12px;
    border: 1px solid alpha({accent}, 0.3);
    padding: 4px;
}}
.reply-input {{
    background-color: alpha({fg}, 0.04);
    border-radius: 6px;
    border: 1px solid alpha({border}, 0.5);
    padding: 8px;
    caret-color: {accent};
    color: {fg};
}}
.reply-input:focus {{
    border-color: {accent};
    box-shadow: 0 0 0 1px alpha({accent}, 0.3);
}}
.reply-hint {{
    font-size: 0.8em;
    color: alpha({fg}, 0.4);
    margin-top: 2px;
}}
"""
```

Note: the `.reply-input` rule now also sets `color: {fg}` so text color matches the overlay foreground.

**Step 3: Update `ActionsWindow.__init__` to accept colors**

Add a `colors: dict` parameter. In the CSS loading section, replace:
```python
css_provider.load_from_string(CSS)
```
with:
```python
css_provider.load_from_string(_build_css(colors))
```

**Step 4: Update `ActionsApp` to load config and pass colors**

In `ActionsApp.do_activate()`, load config and extract colors:
```python
def do_activate(self):
    cfg = load_config()
    colors = cfg.get("overlay", {}).get("colors", {})
    win = ReplyWindow(self, ..., colors=colors)
    win.present()
```

**Step 5: Run tests**

```bash
source .venv/bin/activate && python -m pytest tests/ -x -q
```

**Step 6: Run `make dev` and manually verify**

```bash
make dev
```

Open aside, trigger a reply — the reply box should use the configured overlay colors.

**Step 7: Commit**

```bash
git add aside/reply/window.py
git commit -m "Make reply box colors use overlay.colors from config"
```
