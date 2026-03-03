# Smoke Test Skill Design

## Summary

A Claude Code skill (`/smoke-test`) that boots 3 VMs via VMT, installs aside on each using distro-appropriate methods, and verifies the full stack: daemon, overlay, TTS, and STT.

## VM Targets

| VM Name | Distro | Compositor | Install Method |
|---------|--------|-----------|----------------|
| `aside-arch-sway` | Arch Linux | Sway | AUR (`yay -S aside`) |
| `aside-fedora-kde` | Fedora 43 | KDE Plasma | Manual (`make install`) |
| `aside-ubuntu-kde` | Ubuntu 24.04 | KDE Plasma | Manual (`make install`) |

## Manifests

Each VM gets a dedicated VMT manifest at `~/projects/vmt/manifests/`. Manifests pre-provision all system dependencies so the install steps match what a user would do after following the README.

### System deps baked into manifests

**Arch** — AUR package handles everything. Manifest just needs base-devel, git, yay, sway, pipewire, grim.

**Fedora** — build deps + voice runtime deps:
- Build: gcc, make, meson, ninja-build, cairo-devel, pango-devel, json-c-devel, wayland-devel, wayland-protocols-devel, python3-pip, python3-devel, gtk4-devel, libadwaita-devel, gtk4-layer-shell-devel, gobject-introspection-devel, python3-gobject, python3-cairo
- Voice runtime: pipewire-utils, python3-numpy, portaudio

**Ubuntu** — build deps + voice runtime deps:
- Build: gcc, make, meson, ninja-build, libcairo2-dev, libpango1.0-dev, libjson-c-dev, libwayland-dev, wayland-protocols, python3-pip, python3-dev, python3-venv, libgtk-4-dev, libadwaita-1-dev, libgtk4-layer-shell-dev, libgirepository1.0-dev, python3-gi, python3-gi-cairo, gir1.2-gtk-4.0
- Voice runtime: pipewire, python3-numpy, libportaudio2

## Test Flow (per VM)

### Phase 1 — Boot & wait
```
vmt up <name>
vmt ssh <name> -- "sudo cloud-init status --wait"
```

### Phase 2 — Install aside (distro-specific)
- **Arch:** `yay -S --noconfirm aside`
- **Fedora/Ubuntu:** `git clone https://github.com/scottstav/aside.git && cd aside && make install`

### Phase 3 — Configure & start
```
aside set-key anthropic <key>
systemctl --user enable --now aside-daemon aside-overlay
```

API key read from `~/projects/aside/.env` on the host.

### Phase 4 — Core tests
1. `aside query "say hello"` — exit 0, daemon logs show successful response
2. Overlay socket exists at `/run/user/1000/aside-overlay.sock`
3. No tracebacks in daemon logs

### Phase 5 — Voice add-ons
```
sudo aside enable-tts
sudo aside enable-stt
systemctl --user restart aside-daemon
```
4. `aside query "say hello"` — daemon logs show "Piper TTS loaded"
5. `timeout 5 aside query --mic` — daemon logs show "pw-record" starting, "Whisper model loaded", clean exit

### Phase 6 — Teardown
```
vmt destroy <name>
```

## Success Criteria

After each test step, check `journalctl --user -u aside-daemon`:
- No `FileNotFoundError`, `ModuleNotFoundError`, `ImportError`, or Python tracebacks
- TTS: "Piper TTS loaded" in logs
- STT: "Whisper model loaded" and "pw-record" in logs
- All commands exit 0

## Error Handling

- If a test fails on one VM, continue testing others
- Report all failures at the end
- Always destroy all VMs in cleanup, even on failure

## Skill Location

Project-scoped command: `.claude/commands/smoke-test.md` in the aside repo.

## Artifacts

1. VMT manifests: `aside-arch-sway.toml`, `aside-fedora-kde.toml`, `aside-ubuntu-kde.toml`
2. Claude skill: `.claude/commands/smoke-test.md`
