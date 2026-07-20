# CONVO On-Demand Keyboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `aside view`'s CONVO panel holds the keyboard only while focused (ON_DEMAND), so other apps stay usable beside it.

**Architecture:** State→mode policy is a pure function in `aside/overlay/positioning.py` (pytest-covered); `window.py` maps the returned token to the `Gtk4LayerShell.KeyboardMode` enum and applies it. All code is verbatim in the spec (`docs/superpowers/specs/2026-07-18-convo-on-demand-keyboard-design.md`) — this plan references it.

**Tech Stack:** Python 3, GTK4 + gtk4-layer-shell, pytest.

## Global Constraints

- `positioning.py` must never import `gi`/GTK.
- REPLY/PICKER keep EXCLUSIVE; all non-CONVO/REPLY/PICKER states keep NONE. Behavior identical to today except CONVO.
- Test command: `source .venv/bin/activate && python -m pytest tests/ -x -q`.
- Commit trailer lines (both, every commit):
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01CirL5c2x8Te4dRk5VEY9Rc`
- No `make dev` on the host; VM verification only.

---

### Task 1: `keyboard_mode_for_state` (pure) — TDD

**Files:** Modify `aside/overlay/positioning.py`, `tests/test_overlay_positioning.py`.

- [ ] Step 1: Append failing tests (7 cases: six state values + unknown-string fallback) per the spec's Testing section.
- [ ] Step 2: `python -m pytest tests/test_overlay_positioning.py -x -q` → FAIL (ImportError).
- [ ] Step 3: Append `KEYBOARD_MODES` + `keyboard_mode_for_state` to `positioning.py` — code verbatim from spec.
- [ ] Step 4: Same command → PASS.
- [ ] Step 5: Commit `feat(overlay): keyboard_mode_for_state — pure per-state keyboard policy`.

### Task 2: Window application + docs

**Files:** Modify `aside/overlay/window.py` (import, `_KEYBOARD_MODES` map next to `_LAYER_EDGES`, `_set_state` block at ~229-238), `docs/usage.md` (`aside view` row), `docs/architecture.md` (one sentence on CONVO's on-demand keyboard near the layer-shell mention).

- [ ] Step 1: Apply the three `window.py` edits — code verbatim from spec (the "Replace/with" block was byte-verified against HEAD).
- [ ] Step 2: Docs: usage row gains "panel keeps the keyboard only while focused — click it to reply/select, click away to work elsewhere; Escape dismisses only while focused." Architecture doc gains the CONVO=on-demand note.
- [ ] Step 3: `python -m pytest tests/ -x -q` → all green; `python -c "import ast; ast.parse(open('aside/overlay/window.py').read())"` → OK.
- [ ] Step 4: Commit `feat(overlay): CONVO panel uses on-demand keyboard`.

### Task 3: VM verification + demo GIF

- [ ] Step 1: `vmt up aside-ubuntu-kde` → cloud-init wait → `dev/vm-sync.sh --setup` (fresh VM: apply the compositor-on-seat switch from `dev/vm-demo.sh`'s header comment; install a second GUI app target if needed — `konsole` ships with the manifest).
- [ ] Step 2: Execute the spec's 6 VM checks; the keyboard-focus checks need a focusable second surface: run `konsole` in the kwin session, use `wtype`/`ydotool` (install if needed) or kwin D-Bus to shift focus, and verify keystroke destination via the konsole scrollback / `journalctl` overlay debug lines. Record evidence per check; any check that cannot be honestly automated is recorded as manually-unverifiable with reasoning — do not fake.
- [ ] Step 3: `dev/vm-demo.sh <pr#> aside-panel <demo-script>` for a GIF: panel open with convo → konsole receives typing → click panel → reply streams in.
- [ ] Step 4: Full suite once more; commit any evidence/doc touch-ups.

## Verification checklist (whole plan)

- [ ] 433 tests green (426 + 7 new).
- [ ] VM checks 1-6 recorded.
- [ ] `grep -c "set_keyboard_mode" aside/overlay/window.py` → 2 (init default + `_set_state` single site).
