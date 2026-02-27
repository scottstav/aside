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

## Iterating on Code Changes

After making changes to aside locally:

```bash
# Push changes
cd ~/projects/aside && git add -A && git commit -m "fix: whatever" && git push

# Pull and rebuild in the VM
vmt ssh arch-sway -- "cd /tmp/aside && git pull"

# Rebuild overlay (if C code changed)
vmt ssh arch-sway -- "cd /tmp/aside/overlay && ninja -C build && sudo ninja -C build install"

# Reinstall Python package (if Python code changed)
vmt ssh arch-sway -- "pip install /tmp/aside --break-system-packages"

# Restart services
vmt ssh arch-sway -- "pkill aside-overlay; pkill -f 'python3 -m aside.daemon'"
vmt ssh arch-sway -- 'source ~/.bashrc && nohup python3 -m aside.daemon > /dev/null 2>&1 &'
vmt ssh arch-sway -- 'source ~/.bashrc && nohup aside-overlay > /dev/null 2>&1 &'

# Test again
vmt ssh arch-sway -- 'source ~/.bashrc && aside query "test"'
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
