# aside

Wayland-native LLM desktop assistant. GTK4 overlay + Python daemon + plugins.

## Project Structure

- `aside/overlay/` — GTK4 layer-shell overlay (Python/PyGObject). Streams text with markdown rendering, inline reply, conversation history, picker.
- `aside/` — Python package. `daemon.py` is the main daemon, `cli.py` is the CLI.
- `aside/tools/` — Built-in tool plugins (TOOL_SPEC + run()).
- `data/` — systemd units, desktop entry, config example, waybar module.
- `tests/` — pytest suite. Run: `source .venv/bin/activate && python -m pytest tests/ -x -q`

## Building

```bash
python -m venv .venv --system-site-packages && source .venv/bin/activate && pip install -e .
```

## VM Testing

Use `dev/vm-sync.sh` for the dev loop. VM: `aside-ubuntu-kde` via `~/projects/vmt`.

```bash
cd ~/projects/vmt && source .venv/bin/activate
vmt up aside-ubuntu-kde
vmt ssh aside-ubuntu-kde -- "cloud-init status --wait"
dev/vm-sync.sh --setup          # one command: deps + rsync + install + start
dev/vm-sync.sh                  # iterate: rsync + rebuild + restart
vmt view aside-ubuntu-kde       # open SPICE viewer
```

## Socket Protocol

The overlay listens on `$XDG_RUNTIME_DIR/aside-overlay.sock` (UNIX stream). JSON commands, newline-delimited:

- `{"cmd":"open"}` — show overlay, clear text
- `{"cmd":"text","data":"..."}` — append text (streaming)
- `{"cmd":"done"}` — fade out
- `{"cmd":"clear"}` — dismiss immediately
- `{"cmd":"replace","data":"..."}` — replace all text
- `{"cmd":"thinking"}` — show thinking state
- `{"cmd":"listening"}` — show listening state
- `{"cmd":"input"}` — open conversation picker
- `{"cmd":"reply","conversation_id":"..."}` — open reply input
- `{"cmd":"convo","conversation_id":"..."}` — show conversation history

The daemon listens on `$XDG_RUNTIME_DIR/aside.sock`. The CLI sends queries there.

## After Every Fix

**Always run `make dev` after changing any code.** This reinstalls the Python package and restarts the systemd services so the fix is live on the user's machine immediately. Never commit a fix without installing it first.

## Releasing

When asked to release, do all of these steps:

1. Bump version in `pyproject.toml` and `PKGBUILD`
2. Commit, push, tag (`vX.Y.Z`), push tag
3. Create GitHub release with `gh release create` — put breaking changes and migration notes here
4. Get the sha256sum of the new tarball: `curl -sL "https://github.com/scottstav/aside/archive/vX.Y.Z.tar.gz" | sha256sum`
5. Update `PKGBUILD` sha256sum and `.SRCINFO` (version + source + sha256sum), commit, push
6. Clone AUR repo, copy PKGBUILD and .SRCINFO, commit, push:
   ```bash
   git clone ssh://aur@aur.archlinux.org/aside.git /tmp/aside-aur
   cp PKGBUILD .SRCINFO /tmp/aside-aur/
   cd /tmp/aside-aur && git add -A && git commit -m "update to vX.Y.Z" && git push
   ```

## Important Notes

- The daemon starts via `aside daemon` (CLI subcommand) or `python3 -m aside.daemon`
- Never install Python packages to system Python — always use a venv
- The overlay reads config directly from `~/.config/aside/config.toml`
- LiteLLM handles model routing — set the appropriate API key env var for your provider
