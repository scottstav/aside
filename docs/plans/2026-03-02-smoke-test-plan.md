# Smoke Test Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a `/smoke-test` Claude skill that boots 3 VMs (Arch+Sway, Fedora+KDE, Ubuntu+KDE), installs aside per the README, and verifies the full stack including TTS and STT.

**Architecture:** VMT manifests define each VM's distro, compositor, and pre-provisioned system deps. A Claude command file (`.claude/commands/smoke-test.md`) provides the step-by-step runbook that Claude follows via Bash/SSH. The skill reads the API key from the host `.env`, boots VMs in parallel, runs distro-specific install steps, then tests core query, TTS, and STT on each.

**Tech Stack:** VMT (QEMU/libvirt), cloud-init, Bash, SSH, systemd

---

### Task 1: Create the `aside-arch-sway` VMT manifest

**Files:**
- Create: `~/projects/vmt/manifests/aside-arch-sway.toml`

**Step 1: Write the manifest**

Based on the existing `arch-sway.toml` but with a distinct name and additional packages needed for aside's AUR install + voice add-ons.

```toml
[vm]
name = "aside-arch-sway"
image = "https://geo.mirror.pkgbuild.com/images/latest/Arch-Linux-x86_64-cloudimg.qcow2"
memory = 4096
cpus = 2
disk = 15

[provision]
packages = [
    "openssh",
    "sway", "foot", "grim",
    "pipewire", "wireplumber", "pipewire-pulse",
    "socat", "git", "base-devel",
]
compositor = "sway"
compositor_cmd = "sway"
display_server = "wayland"
screenshot_tool = "grim"

[provision.env]
XDG_RUNTIME_DIR = "/run/user/1000"
WLR_RENDERER = "pixman"
WLR_LIBINPUT_NO_DEVICES = "1"

[ssh]
user = "arch"
port = 22
```

Notes:
- Memory bumped to 4096 (Whisper model loading needs RAM)
- Disk bumped to 15 (AUR build + voice models)
- No extra voice deps needed — the AUR `aside` package depends on `pipewire`, `portaudio`, and yay will pull `python-numpy` as a dep of `python-faster-whisper`

**Step 2: Verify manifest parses**

Run: `cd ~/projects/vmt && source .venv/bin/activate && python -c "from vmt.manifest import load_manifest; m = load_manifest('aside-arch-sway'); print(m)"`

Expected: No errors, prints manifest dict.

**Step 3: Commit**

```bash
cd ~/projects/vmt
git add manifests/aside-arch-sway.toml
git commit -m "add aside-arch-sway manifest for smoke testing"
```

---

### Task 2: Create the `aside-fedora-kde` VMT manifest

**Files:**
- Create: `~/projects/vmt/manifests/aside-fedora-kde.toml`

**Step 1: Write the manifest**

```toml
[vm]
name = "aside-fedora-kde"
image = "https://download.fedoraproject.org/pub/fedora/linux/releases/43/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-43-1.6.x86_64.qcow2"
memory = 4096
cpus = 2
disk = 20

[provision]
packages = [
    "plasma-desktop", "plasma-workspace", "sddm", "kwin-wayland",
    "konsole", "grim",
    "pipewire", "wireplumber", "pipewire-pulseaudio",
    "socat", "git",
    # build deps for aside
    "gcc", "make", "meson", "ninja-build",
    "cairo-devel", "pango-devel", "json-c-devel",
    "wayland-devel", "wayland-protocols-devel",
    "python3-pip", "python3-devel",
    "gtk4-devel", "libadwaita-devel", "gtk4-layer-shell-devel",
    "gobject-introspection-devel", "python3-gobject", "python3-cairo",
    # voice runtime deps
    "pipewire-utils", "python3-numpy", "portaudio",
]
compositor = "kwin"
compositor_cmd = "startplasma-wayland"
display_server = "wayland"
screenshot_tool = "grim"

[provision.env]
XDG_RUNTIME_DIR = "/run/user/1000"

[ssh]
user = "fedora"
port = 22
```

**Step 2: Verify manifest parses**

Run: `cd ~/projects/vmt && source .venv/bin/activate && python -c "from vmt.manifest import load_manifest; m = load_manifest('aside-fedora-kde'); print(m)"`

Expected: No errors.

**Step 3: Commit**

```bash
cd ~/projects/vmt
git add manifests/aside-fedora-kde.toml
git commit -m "add aside-fedora-kde manifest for smoke testing"
```

---

### Task 3: Create the `aside-ubuntu-kde` VMT manifest

**Files:**
- Create: `~/projects/vmt/manifests/aside-ubuntu-kde.toml`

**Step 1: Write the manifest**

```toml
[vm]
name = "aside-ubuntu-kde"
image = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
memory = 4096
cpus = 2
disk = 20

[provision]
packages = [
    "kde-plasma-desktop", "sddm", "kwin-wayland",
    "konsole", "grim",
    "pipewire", "wireplumber", "pipewire-pulse",
    "socat", "git",
    # build deps for aside
    "gcc", "make", "meson", "ninja-build",
    "libcairo2-dev", "libpango1.0-dev", "libjson-c-dev",
    "libwayland-dev", "wayland-protocols",
    "python3-pip", "python3-dev", "python3-venv",
    "libgtk-4-dev", "libadwaita-1-dev", "libgtk4-layer-shell-dev",
    "libgirepository1.0-dev", "python3-gi", "python3-gi-cairo", "gir1.2-gtk-4.0",
    # voice runtime deps
    "python3-numpy", "libportaudio2",
]
compositor = "kwin"
compositor_cmd = "startplasma-wayland"
display_server = "wayland"
screenshot_tool = "grim"

[provision.env]
XDG_RUNTIME_DIR = "/run/user/1000"

[ssh]
user = "ubuntu"
port = 22
```

Notes:
- Ubuntu cloud images use `ubuntu` as the default user
- `pipewire` package on Ubuntu includes `pw-record` (no separate `pipewire-utils`)
- `kde-plasma-desktop` is the Ubuntu meta-package for KDE Plasma

**Step 2: Verify manifest parses**

Run: `cd ~/projects/vmt && source .venv/bin/activate && python -c "from vmt.manifest import load_manifest; m = load_manifest('aside-ubuntu-kde'); print(m)"`

Expected: No errors.

**Step 3: Commit**

```bash
cd ~/projects/vmt
git add manifests/aside-ubuntu-kde.toml
git commit -m "add aside-ubuntu-kde manifest for smoke testing"
```

---

### Task 4: Create the `.claude/commands/smoke-test.md` skill

**Files:**
- Create: `/home/ifit/projects/aside/.claude/commands/smoke-test.md`

**Step 1: Write the skill file**

The skill is a detailed runbook for Claude to follow. It uses Bash to invoke `vmt` commands and SSH into VMs. See full content below.

```markdown
---
allowed-tools: Bash, Read, Grep, Glob
description: Boot 3 VMs, install aside, and verify full stack (daemon, overlay, TTS, STT).
---

You are a smoke-test runner for aside. You will boot 3 VMs using VMT, install aside on each, and verify the entire stack works.

## Prerequisites

Before starting, verify:
1. VMT is available: `cd ~/projects/vmt && source .venv/bin/activate && vmt --help`
2. Read the API key from `~/projects/aside/.env` — extract the value after `ANTHROPIC_API_KEY=`. You will inject this into each VM.

## VM Targets

| Name | Distro | Compositor | Install Method | SSH User |
|------|--------|-----------|----------------|----------|
| `aside-arch-sway` | Arch Linux | Sway | AUR (`yay`) | `arch` |
| `aside-fedora-kde` | Fedora 43 | KDE Plasma | Manual (`make install`) | `fedora` |
| `aside-ubuntu-kde` | Ubuntu 24.04 | KDE Plasma | Manual (`make install`) | `ubuntu` |

## Phase 1: Boot all VMs (parallel)

Run all 3 in parallel:

```bash
cd ~/projects/vmt && source .venv/bin/activate
vmt up aside-arch-sway
vmt up aside-fedora-kde
vmt up aside-ubuntu-kde
```

Then wait for cloud-init on each:

```bash
vmt ssh aside-arch-sway -- "sudo cloud-init status --wait"
vmt ssh aside-fedora-kde -- "sudo cloud-init status --wait"
vmt ssh aside-ubuntu-kde -- "sudo cloud-init status --wait"
```

Cloud-init may take 5-15 minutes on Fedora/Ubuntu (KDE is ~800 packages). Use `timeout 900` if needed.

## Phase 2: Install aside (per-VM, distro-specific)

### Arch (AUR)

Arch cloud images don't ship with `yay`. Install it first:

```bash
vmt ssh aside-arch-sway -- "git clone https://aur.archlinux.org/yay-bin.git /tmp/yay-bin && cd /tmp/yay-bin && makepkg -si --noconfirm"
```

Then install aside:

```bash
vmt ssh aside-arch-sway -- "yay -S --noconfirm aside"
```

### Fedora (manual)

Build deps are pre-provisioned in the manifest. Just clone and install:

```bash
vmt ssh aside-fedora-kde -- "git clone https://github.com/scottstav/aside.git ~/aside && cd ~/aside && make install"
```

Verify `~/.local/bin` is in PATH:

```bash
vmt ssh aside-fedora-kde -- "which aside || echo 'PATH issue: add ~/.local/bin to PATH'"
```

If not in PATH, fix it:

```bash
vmt ssh aside-fedora-kde -- "echo 'export PATH=\$HOME/.local/bin:\$PATH' >> ~/.bashrc && source ~/.bashrc"
```

### Ubuntu (manual)

Same as Fedora:

```bash
vmt ssh aside-ubuntu-kde -- "git clone https://github.com/scottstav/aside.git ~/aside && cd ~/aside && make install"
```

Check PATH the same way and fix if needed.

## Phase 3: Configure & start services

For each VM, set the API key and start services. Use the API key you read from `.env` in the prerequisites step.

```bash
vmt ssh <name> -- "aside set-key anthropic <API_KEY>"
vmt ssh <name> -- "systemctl --user enable --now aside-daemon aside-overlay"
```

Wait 3 seconds for the daemon to initialize, then verify it's running:

```bash
vmt ssh <name> -- "systemctl --user is-active aside-daemon"
```

Expected output: `active`

## Phase 4: Core tests

For each VM, run these tests. Track pass/fail per VM.

### Test 1: Basic query

```bash
vmt ssh <name> -- "aside query 'say hello in one sentence'"
```

**Check:** Exit code is 0.

**Check logs:**

```bash
vmt ssh <name> -- "journalctl --user -u aside-daemon --no-pager -n 20"
```

**Pass if:** No Python tracebacks. Log shows "Conversation ... complete".

### Test 2: Overlay socket exists

```bash
vmt ssh <name> -- "test -S /run/user/1000/aside-overlay.sock && echo 'OVERLAY OK' || echo 'OVERLAY MISSING'"
```

**Pass if:** Output is `OVERLAY OK`.

### Test 3: Daemon socket exists

```bash
vmt ssh <name> -- "test -S /run/user/1000/aside.sock && echo 'DAEMON OK' || echo 'DAEMON MISSING'"
```

**Pass if:** Output is `DAEMON OK`.

## Phase 5: Voice add-ons

### Install TTS and STT

For Arch, `aside` is installed system-wide at `/usr/bin/aside`, so `sudo aside` works directly.

For Fedora/Ubuntu, `aside` is at `~/.local/bin/aside`, which is NOT in root's PATH. Use the full path:

**Arch:**
```bash
vmt ssh aside-arch-sway -- "sudo aside enable-tts"
vmt ssh aside-arch-sway -- "sudo aside enable-stt"
```

**Fedora/Ubuntu:**
```bash
vmt ssh <name> -- "sudo \$(which aside) enable-tts"
vmt ssh <name> -- "sudo \$(which aside) enable-stt"
```

Then restart the daemon on all VMs:

```bash
vmt ssh <name> -- "systemctl --user restart aside-daemon"
```

Wait 3 seconds for daemon to reinitialize.

### Test 4: TTS loads

```bash
vmt ssh <name> -- "aside query 'say hello in one sentence'"
```

**Check logs:**

```bash
vmt ssh <name> -- "journalctl --user -u aside-daemon --no-pager -n 30"
```

**Pass if:** Logs contain "Piper TTS loaded" (case-insensitive search for "piper" and "loaded").

### Test 5: STT / mic pipeline

```bash
vmt ssh <name> -- "timeout 8 aside query --mic; echo EXIT=\$?"
```

Expected: exit code 124 (timeout) or 0 (no speech detected). Both are acceptable — the VM has no mic input.

**Check logs:**

```bash
vmt ssh <name> -- "journalctl --user -u aside-daemon --no-pager -n 30 --since '30 sec ago'"
```

**Pass if:**
- Logs contain "pw-record" (audio capture started)
- Logs contain "Whisper model loaded" or "whisper" (STT initialized)
- No `FileNotFoundError` or `ModuleNotFoundError` in logs

## Phase 6: Results & teardown

### Print results

Print a summary table:

```
=== ASIDE SMOKE TEST RESULTS ===

| VM                  | Query | Overlay | TTS  | STT  |
|---------------------|-------|---------|------|------|
| aside-arch-sway     | PASS  | PASS    | PASS | PASS |
| aside-fedora-kde    | PASS  | PASS    | PASS | PASS |
| aside-ubuntu-kde    | PASS  | PASS    | PASS | PASS |
```

### Teardown

Always destroy all VMs, even if tests failed:

```bash
cd ~/projects/vmt && source .venv/bin/activate
vmt destroy aside-arch-sway
vmt destroy aside-fedora-kde
vmt destroy aside-ubuntu-kde
```

### Final verdict

If all tests passed on all VMs: report SUCCESS.
If any test failed: report FAILURE with the specific VM and test that failed, and include the relevant log output.
```

**Step 2: Create the `.claude/commands/` directory**

```bash
mkdir -p /home/ifit/projects/aside/.claude/commands
```

**Step 3: Commit**

```bash
cd /home/ifit/projects/aside
git add .claude/commands/smoke-test.md
git commit -m "add /smoke-test skill for cross-distro VM testing"
```

---

### Task 5: Verify the skill loads

**Step 1: Check the skill is visible**

From the aside project directory, verify Claude Code sees the command:

```bash
cd /home/ifit/projects/aside
# The skill should appear as /smoke-test in Claude Code
ls -la .claude/commands/smoke-test.md
```

**Step 2: Run `~/dotfiles/sync-claude.sh`**

Per CLAUDE.md instructions, sync the new command to dotfiles:

```bash
~/dotfiles/sync-claude.sh
```

---

### Task 6: Push all changes

**Step 1: Push VMT manifests**

```bash
cd ~/projects/vmt
git push
```

**Step 2: Push aside skill**

```bash
cd ~/projects/aside
git push
```
