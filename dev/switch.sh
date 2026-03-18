#!/bin/bash
# Switch between AUR-installed aside and a local editable build.
#
#   dev/switch.sh local    — use the local repo (editable install)
#   dev/switch.sh system  — use the AUR package
#   dev/switch.sh          — show which is active
#
# The AUR package stays installed either way. "local" shadows it by
# putting symlinks in ~/.local/bin and user systemd units in
# ~/.config/systemd/user. "system" removes those shadows so the
# AUR paths (/usr/bin, /usr/lib/systemd/user) take over.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/.venv"
LOCAL_BIN="$HOME/.local/bin"
USER_UNITS="$HOME/.config/systemd/user"
BINS=(aside aside-overlay)

is_local() {
    [[ -L "$LOCAL_BIN/aside" ]] && [[ "$(readlink "$LOCAL_BIN/aside")" == "$VENV"/* ]]
}

status() {
    if is_local; then
        echo "active: local  ($VENV)"
    else
        echo "active: system  ($(command -v aside 2>/dev/null || echo '/usr/bin/aside'))"
    fi
}

activate_local() {
    # Create venv if needed
    if [[ ! -d "$VENV" ]]; then
        echo "==> Creating venv at $VENV"
        python3 -m venv "$VENV" --system-site-packages
    fi

    echo "==> Installing editable build"
    "$VENV/bin/pip" install -q -e "$REPO_DIR"

    # Symlink entry points to shadow /usr/bin
    mkdir -p "$LOCAL_BIN"
    for cmd in "${BINS[@]}"; do
        ln -sf "$VENV/bin/$cmd" "$LOCAL_BIN/$cmd"
    done

    # User systemd units shadow /usr/lib/systemd/user
    mkdir -p "$USER_UNITS"
    cp "$REPO_DIR/data/aside-daemon.service" "$USER_UNITS/"
    cp "$REPO_DIR/data/aside-overlay.service" "$USER_UNITS/"

    systemctl --user daemon-reload
    systemctl --user restart aside-daemon aside-overlay

    echo "==> Switched to local build"
    echo "    Code changes are live — just restart services:"
    echo "    systemctl --user restart aside-daemon aside-overlay"
}

activate_system() {
    # Remove local symlinks
    for cmd in "${BINS[@]}"; do
        rm -f "$LOCAL_BIN/$cmd"
    done

    # Remove user unit overrides — falls back to AUR's /usr/lib/systemd/user
    rm -f "$USER_UNITS/aside-daemon.service"
    rm -f "$USER_UNITS/aside-overlay.service"

    systemctl --user daemon-reload
    systemctl --user restart aside-daemon aside-overlay

    echo "==> Switched to AUR build"
}

case "${1:-}" in
    local)   activate_local ;;
    system) activate_system ;;
    "")      status ;;
    *)       echo "Usage: $0 [local|system]" >&2; exit 1 ;;
esac
