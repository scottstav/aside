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

Fast loop — restore the golden snapshot (seconds, offline, deterministic):

```bash
cd ~/projects/vmt && source .venv/bin/activate
vmt restore aside-ubuntu-kde golden
virsh -c qemu:///system start vmt-aside-ubuntu-kde   # NOT `vmt up` — up recreates the disk and DESTROYS the snapshot
cd ~/projects/aside && dev/vm-sync.sh                # rsync + install + restart services
vmt view aside-ubuntu-kde                            # optional SPICE viewer
```

Rebuild the golden snapshot only if it is lost or must change (full provision,
~15 min): `dev/vm-golden.sh`. A second golden exists for the AUR-package test
bed: `vmt restore arch-sway golden`.

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

Run `make dev` while iterating so the change is live on this machine right away.

A fix is done when it's released, not when it's on a branch. Once the tests pass, fast-forward it into master (no PR: there's no CI or reviewer for one to wait on) and run `make release`. Then `make system` if this machine was on the dev build, so it runs the released package.

## Releasing

`make release` (patch bump) or `make release V=0.9.0`. `make release-check` runs the gate alone and publishes nothing.

`dev/release.sh` does every step: the test suite plus a live query through aside's own streaming code (`dev/smoke.py`) against the litellm that will actually ship, version bump, tag, GitHub release, tarball sha256 into `PKGBUILD`/`.SRCINFO`, a real `makepkg` build, install here (one pkexec prompt), then the AUR push. Nothing is published until the gate passes, and the AUR is pushed only after the package is installed and running here.

The live query matters because the PKGBUILD installs litellm unpinned at build time, so every release is also a litellm upgrade, and the unit tests mock `litellm.completion`.

Releases stay deliberate and local. Publishing from CI on every merge was tried and dropped (PR #12), so don't re-propose it.

## Important Notes

- The daemon starts via `aside daemon` (CLI subcommand) or `python3 -m aside.daemon`
- Never install Python packages to system Python — always use a venv
- The overlay reads config directly from `~/.config/aside/config.toml`
- LiteLLM handles model routing — set the appropriate API key env var for your provider
