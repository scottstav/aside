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

Run all 3 in parallel using separate Bash tool calls:

```bash
cd ~/projects/vmt && source .venv/bin/activate
vmt up aside-arch-sway
```
```bash
cd ~/projects/vmt && source .venv/bin/activate
vmt up aside-fedora-kde
```
```bash
cd ~/projects/vmt && source .venv/bin/activate
vmt up aside-ubuntu-kde
```

Then wait for cloud-init on each (these can also run in parallel):

```bash
vmt ssh aside-arch-sway -- "sudo cloud-init status --wait"
```
```bash
vmt ssh aside-fedora-kde -- "sudo cloud-init status --wait"
```
```bash
vmt ssh aside-ubuntu-kde -- "sudo cloud-init status --wait"
```

Cloud-init may take 5-15 minutes on Fedora/Ubuntu (KDE is ~800 packages). Use timeout 900 on the Bash tool if needed.

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
vmt ssh aside-fedora-kde -- "echo 'export PATH=\$HOME/.local/bin:\$PATH' >> ~/.bashrc"
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
