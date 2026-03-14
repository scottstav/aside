# VM Testing with vmt

End-to-end testing of aside in ephemeral QEMU VMs using [vmt](https://github.com/scottstav/vmt).

## Prerequisites

- vmt installed at `~/projects/vmt` with its venv
- Host packages: `qemu-full libvirt virt-viewer`
- User in `libvirt` group
- `libvirtd` running

## Quick Start

```bash
cd ~/projects/vmt && source .venv/bin/activate

# Boot an Arch + Sway VM (downloads cloud image on first run, ~2min)
vmt up arch-sway

# Wait for cloud-init to finish provisioning
vmt ssh arch-sway -- "cloud-init status --wait"

# Install build deps + build aside overlay (C component)
vmt ssh arch-sway -- "sudo pacman -S --noconfirm meson ninja cairo pango json-c wayland-protocols python python-pip"
vmt ssh arch-sway -- "git clone https://github.com/scottstav/aside.git /tmp/aside"
vmt ssh arch-sway -- "cd /tmp/aside/overlay && meson setup build --prefix=/usr && ninja -C build && sudo ninja -C build install"

# Install aside Python package
vmt ssh arch-sway -- "pip install /tmp/aside --break-system-packages"

# Set API key (replace with actual key)
vmt ssh arch-sway -- "echo 'export ANTHROPIC_API_KEY=sk-...' >> ~/.bashrc"

# Start the daemon + overlay
vmt ssh arch-sway -- 'source ~/.bashrc && nohup python3 -m aside.daemon > /dev/null 2>&1 &'
vmt ssh arch-sway -- 'source ~/.bashrc && nohup aside-overlay > /dev/null 2>&1 &'

# Test a query
vmt ssh arch-sway -- 'source ~/.bashrc && aside query "Hello, what are you?"'
```

## Interactive Testing (SPICE)

Open the VM desktop in a SPICE viewer:

```bash
vmt view arch-sway
```

The VM auto-logs in and launches sway on the DRM display. Open a terminal with `Super+Return`. The default password is `vmt`.

## Iterating on Code Changes (Fast Dev Loop)

Use `dev/vm-sync.sh` for rapid iteration. It rsyncs your local changes directly to the VM over SSH — no git commit/push/pull needed.

```bash
# First time: boot VM and do initial setup
cd ~/projects/vmt && source .venv/bin/activate
vmt up aside-ubuntu-kde
vmt ssh aside-ubuntu-kde -- "cloud-init status --wait"

# Initial build + install
cd ~/projects/aside
dev/vm-sync.sh --setup

# Set your API key in the VM
dev/vm-sync.sh --ssh "echo 'export ANTHROPIC_API_KEY=sk-...' >> ~/.bashrc"

# Open the desktop viewer
cd ~/projects/vmt && source .venv/bin/activate && vmt view aside-ubuntu-kde
```

Then iterate:

```bash
# Make changes locally, then sync + rebuild + restart (full cycle)
dev/vm-sync.sh

# Only changed Python code?
dev/vm-sync.sh --python-only

# Only changed C overlay code?
dev/vm-sync.sh --overlay-only

# Sync + rebuild + run a test query
dev/vm-sync.sh --query "Hello, what are you?"

# Check logs
dev/vm-sync.sh --logs

# Run arbitrary commands in the VM
dev/vm-sync.sh --ssh "journalctl --user -u test-compositor -n 20"
```

### Old method (git-based, slower)

If rsync isn't available, you can still use the git push/pull method:

```bash
cd ~/projects/aside && git add -A && git commit -m "fix: whatever" && git push
vmt ssh aside-ubuntu-kde -- "cd ~/aside && git pull"
vmt ssh aside-ubuntu-kde -- "cd ~/aside/overlay && ninja -C build && sudo ninja -C build install"
vmt ssh aside-ubuntu-kde -- "cd ~/aside && .venv/bin/pip install -e . -q"
```

## Screenshots

```bash
# Take a screenshot from inside the VM
vmt ssh arch-sway -- "WAYLAND_DISPLAY=wayland-1 grim /tmp/shot.png"

# Pull it to host
vmt screenshot arch-sway /tmp/shot.png /tmp/local-shot.png
```

## Cleanup

```bash
vmt destroy arch-sway
```

## Troubleshooting

### No internet in VM
Docker's FORWARD chain can block virbr0 traffic. vmt tries to fix this automatically on `vmt up`, but if it fails (permissions), run:
```bash
sudo iptables -I DOCKER-USER -i virbr0 -j ACCEPT
sudo iptables -I DOCKER-USER -o virbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
```

### Cloud-init package install fails
If pacman fails during cloud-init, the keyring might not be initialized. Run manually:
```bash
vmt ssh arch-sway -- "sudo pacman-key --init && sudo pacman-key --populate archlinux"
vmt ssh arch-sway -- "sudo pacman -Syu --noconfirm"
```

### Overlay shows box but no text
Restart the overlay — it may have connected to a stale Wayland socket:
```bash
vmt ssh arch-sway -- "pkill aside-overlay"
vmt ssh arch-sway -- 'WAYLAND_DISPLAY=wayland-1 nohup aside-overlay > /dev/null 2>&1 &'
```

### SPICE shows TTY login instead of sway
The VM uses TTY autologin. If it's not working, log in with user `arch`, password `vmt`, then run `sway`.
