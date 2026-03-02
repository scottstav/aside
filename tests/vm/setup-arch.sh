#!/bin/bash
# Provision a fresh Arch+Sway VM for aside testing.
# Run once after cloud-init finishes. Assumes arch-sway vmt manifest.
#
# Usage (from host):
#   vmt ssh arch-sway -- "bash /tmp/setup-arch.sh"
set -euo pipefail

echo "=== aside VM setup (Arch + Sway) ==="

# ── System update ─────────────────────────────────────────────────────────
echo "--- Updating system ---"
sudo pacman -Syu --noconfirm

# ── Clone and build ───────────────────────────────────────────────────────
echo "--- Cloning aside ---"
rm -rf ~/aside
git clone https://github.com/scottstav/aside.git ~/aside
cd ~/aside

echo "--- Building package (makepkg -si) ---"
makepkg -si --noconfirm

# ── Runtime extras (not in PKGBUILD depends) ──────────────────────────────
# xdg-utils: aside open uses xdg-open
# emacs:     already in cloud image; used as markdown viewer
# foot:      already in cloud image; terminal for aside-input
sudo pacman -S --noconfirm --needed xdg-utils perl-file-mimeinfo

# ── xdg-open: set mousepad as handler for markdown/text ───────────────────
sudo pacman -S --noconfirm --needed mousepad
xdg-mime default mousepad.desktop text/markdown
xdg-mime default mousepad.desktop text/x-markdown
xdg-mime default mousepad.desktop text/plain

# ── API key ───────────────────────────────────────────────────────────────
mkdir -p ~/.config/aside
cat > ~/.config/aside/env << 'ENV'
ANTHROPIC_API_KEY=your-key-here
ENV

# ── Wayland display for SPICE testing ─────────────────────────────────────
# The vmt cloud-init starts a headless test-compositor (wayland-1) for
# screenshot testing. The DRM sway session (SPICE viewer) gets a higher
# number. Point user services at the DRM display so the overlay and GTK
# windows appear in the SPICE session you're actually looking at.
_drm_display=$(ls /run/user/$(id -u)/wayland-* 2>/dev/null \
    | grep -v lock | sort -V | tail -1 | xargs basename)
if [ -n "$_drm_display" ]; then
    echo "--- Using Wayland display: $_drm_display ---"
    systemctl --user set-environment WAYLAND_DISPLAY="$_drm_display"
fi

# ── Start services ────────────────────────────────────────────────────────
echo "--- Starting aside services ---"
systemctl --user daemon-reload
systemctl --user enable --now aside-daemon aside-overlay

# Wait for socket
for i in $(seq 1 10); do
    [ -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/aside.sock" ] && break
    sleep 1
done

# ── Verify ────────────────────────────────────────────────────────────────
echo ""
echo "--- Verification ---"
systemctl --user status aside-daemon --no-pager
echo ""
systemctl --user status aside-overlay --no-pager
echo ""
aside --help >/dev/null && echo "OK: aside CLI works"
echo ""
echo "=== Setup complete. Open SPICE viewer to test GUI. ==="
