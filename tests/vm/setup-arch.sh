#!/bin/bash
# Provision a fresh Arch+Sway VM for aside testing.
# Run once after cloud-init finishes. Assumes arch-sway vmt manifest.
# Expects ~/aside to already contain the source tree (see vm-test.sh).
set -euo pipefail

echo "=== aside VM setup (Arch + Sway) ==="

# ── System update ─────────────────────────────────────────────────────────
echo "--- Updating system ---"
sudo pacman -Syu --noconfirm

# ── Build ─────────────────────────────────────────────────────────────────
cd ~/aside

# makepkg expects a tarball named $pkgname-$pkgver.tar.gz containing a
# top-level directory $pkgname-$pkgver/. Create it from the local tree
# so makepkg uses our code instead of downloading from GitHub.
_pkgver=$(grep '^pkgver=' PKGBUILD | cut -d= -f2)
echo "--- Creating local source tarball (aside-${_pkgver}) ---"
mkdir -p src
ln -sfn "$(pwd)" "src/aside-${_pkgver}"
tar czf "aside-${_pkgver}.tar.gz" \
    --exclude=.git --exclude=.venv --exclude=builddir \
    --exclude=src --exclude='*.pkg.tar.zst' --exclude='*.tar.gz' \
    --exclude=pkg --exclude=__pycache__ --exclude='*.egg-info' \
    -C src "aside-${_pkgver}"

echo "--- Building package (makepkg -si) ---"
makepkg -si --noconfirm --skipchecksums

# ── Runtime extras (not in PKGBUILD depends) ──────────────────────────────
# xdg-utils: aside open uses xdg-open
# emacs:     already in cloud image; used as markdown viewer
# foot:      already in cloud image; terminal emulator
sudo pacman -S --noconfirm --needed xdg-utils perl-file-mimeinfo

# ── xdg-open: set mousepad as handler for markdown/text ───────────────────
sudo pacman -S --noconfirm --needed mousepad
xdg-mime default mousepad.desktop text/markdown
xdg-mime default mousepad.desktop text/x-markdown
xdg-mime default mousepad.desktop text/plain

# ── API key ───────────────────────────────────────────────────────────────
# Injected by vm-test.sh from host env. Skip if already present.
if [ ! -f ~/.config/aside/env ]; then
    echo "WARNING: No API key found. Run on host: vmt ssh $VM -- \"mkdir -p ~/.config/aside && echo ANTHROPIC_API_KEY=\$ANTHROPIC_API_KEY > ~/.config/aside/env\""
fi

# ── Wayland display for SPICE testing ─────────────────────────────────────
# Cloud-init starts a headless compositor (wayland-1). The DRM sway session
# (SPICE viewer) creates a higher-numbered socket. Wait for it so the
# overlay appears in the session you're actually looking at.
echo "--- Waiting for DRM Wayland display ---"
for _i in $(seq 1 30); do
    _drm_display=$(ls /run/user/$(id -u)/wayland-* 2>/dev/null \
        | grep -v lock | sort -V | tail -1 | xargs basename)
    # wayland-0 or wayland-1 is the headless compositor; DRM session is higher
    if [ -n "$_drm_display" ] && [ "$_drm_display" != "wayland-0" ] && [ "$_drm_display" != "wayland-1" ]; then
        break
    fi
    sleep 1
done
echo "--- Using Wayland display: ${_drm_display:-wayland-1} ---"
systemctl --user set-environment WAYLAND_DISPLAY="${_drm_display:-wayland-1}"

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
