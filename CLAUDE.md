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
- `{"cmd":"move","to":"top-left"}` / `{"cmd":"move","step":"left"}` / `{"cmd":"move","reset":true}` — reposition overlay between the six anchor slots (session-only; exactly one key per command)
- `{"cmd":"resize","width":"+50","max_height":"300"}` / `{"cmd":"resize","reset":true}` — resize overlay; `"+N"`/`"-N"` relative, bare number absolute (session-only)

The daemon listens on `$XDG_RUNTIME_DIR/aside.sock`. The CLI sends queries there.

## After Every Fix

**Always run `make dev` after changing any code.** This reinstalls the Python package and restarts the systemd services so the fix is live on the user's machine immediately. Never commit a fix without installing it first.

## Releasing

Releases are automated by `.github/workflows/release.yml` (python-semantic-release, configured in `pyproject.toml` under `[tool.semantic_release]`). Merging Conventional-Commit work to `master` is the release action:

- `feat:` → minor bump, `fix:`/`perf:` → patch; while we're on 0.x, breaking changes also bump minor (`major_on_zero = false`). `docs:`/`chore:`/`build:`/`ci:` cut no release.
- The workflow bumps `pyproject.toml` + `PKGBUILD`, commits `release: vX.Y.Z`, tags, publishes the GitHub release + CHANGELOG.md, fills the real tarball sha256 into `PKGBUILD`/`.SRCINFO` on master, and pushes the update to the AUR.
- Needs the `AUR_SSH_PRIVATE_KEY` repo secret (private key for the AUR maintainer account). If the AUR job fails, the tag/GitHub release still exist — fix and re-run the job from the Actions UI.

Manual fallback if the workflow is broken: bump both version fields, commit + tag `vX.Y.Z` + push, `gh release create`, sha256 the tarball (`curl -sL "https://github.com/scottstav/aside/archive/vX.Y.Z.tar.gz" | sha256sum`) into `PKGBUILD`/`.SRCINFO`, then clone `ssh://aur@aur.archlinux.org/aside.git`, copy `PKGBUILD` + `.SRCINFO` in, commit "update to vX.Y.Z", push.

## Important Notes

- The daemon starts via `aside daemon` (CLI subcommand) or `python3 -m aside.daemon`
- Never install Python packages to system Python — always use a venv
- The overlay reads config directly from `~/.config/aside/config.toml`
- LiteLLM handles model routing — set the appropriate API key env var for your provider
