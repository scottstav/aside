#!/usr/bin/env bash
# Fast dev loop for aside on a vmt VM.
#
# --setup runs the EXACT commands from the README (manual install section):
#   1. apt install <deps from docs/install.md>
#   2. git clone https://github.com/scottstav/aside.git && cd aside && make install
#   3. aside set-key ...
#   4. systemctl --user enable --now aside-daemon aside-overlay
#
# After setup, iterate with rsync (no git commit/push needed):
#   dev/vm-sync.sh                    # rsync + make install + restart
#   dev/vm-sync.sh --overlay-only     # only rebuild C overlay
#   dev/vm-sync.sh --python-only      # only reinstall Python package
#   dev/vm-sync.sh --query "hello"    # sync + rebuild + restart + test query
#
# Requires: VM already booted with `vmt up aside-ubuntu-kde`

set -euo pipefail

VM_NAME="${VM_NAME:-aside-ubuntu-kde}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY="$HOME/.local/share/vmt/id_ed25519"
VMT_DIR="$HOME/projects/vmt"

# The setup clones to ~/aside, so iteration syncs there too
REMOTE_DIR="/home/ubuntu/aside"

# --- resolve VM IP -----------------------------------------------------------

get_vm_ip() {
    cd "$VMT_DIR" && source .venv/bin/activate
    python3 -c "
from vmt.vm import VMManager
from pathlib import Path
mgr = VMManager(manifest_dirs=[Path('manifests')])
info = mgr.get_info('$VM_NAME')
mgr.close()
if info: print(info['ip'])
else: exit(1)
" 2>/dev/null
}

VM_IP="$(get_vm_ip)" || { echo "ERROR: VM '$VM_NAME' is not running. Run: vmt up $VM_NAME"; exit 1; }
SSH_OPTS="-o StrictHostKeyChecking=no -o LogLevel=ERROR -i $SSH_KEY"
SSH_CMD="ssh $SSH_OPTS ubuntu@$VM_IP"

ssh_run() { $SSH_CMD "$@"; }

# --- actions ------------------------------------------------------------------

do_setup() {
    # -------------------------------------------------------------------------
    # This runs the EXACT commands from README.md and docs/install.md.
    # If these fail, the README is wrong and needs updating.
    # -------------------------------------------------------------------------

    echo "=> [README step 1] Installing system dependencies (docs/install.md)"
    ssh_run "sudo apt-get update -qq && sudo apt-get install -y -qq \
        meson ninja-build pkg-config gcc python3-venv python3-pip python3-dev \
        libwayland-dev wayland-protocols \
        libcairo2-dev libpango1.0-dev libjson-c-dev \
        libpipewire-0.3-dev \
        libgtk-4-dev gobject-introspection libgirepository1.0-dev valac \
        python3-gi python3-gi-cairo gir1.2-gtk-4.0 git"

    echo "=> [README step 1b] Building gtk4-layer-shell from source (docs/install.md)"
    ssh_run "rm -rf /tmp/gtk4-layer-shell && \
        git clone https://github.com/wmww/gtk4-layer-shell.git /tmp/gtk4-layer-shell && \
        cd /tmp/gtk4-layer-shell && meson setup build && ninja -C build && sudo ninja -C build install && \
        sudo ldconfig"

    echo "=> [README step 2] git clone + make install"
    ssh_run "rm -rf ~/aside && git clone https://github.com/scottstav/aside.git ~/aside && cd ~/aside && make install"

    do_sync_env

    echo ""
    echo "=> Setup complete! Remaining README steps:"
    echo "   systemctl --user enable --now aside-daemon aside-overlay"
    echo ""
    echo "   Or: dev/vm-sync.sh --ssh \"systemctl --user enable --now aside-daemon aside-overlay\""
    echo ""
    echo "=> API keys were copied from .env (if present). To iterate: dev/vm-sync.sh"
}

do_sync_env() {
    local env_file="$PROJECT_DIR/.env"
    if [ -f "$env_file" ]; then
        echo "=> syncing .env to VM"
        ssh_run "mkdir -p ~/.config/aside"
        scp -q $SSH_OPTS "$env_file" "ubuntu@$VM_IP:~/.config/aside/env"
        ssh_run "chmod 600 ~/.config/aside/env"
    fi
}

do_rsync() {
    echo "=> rsync to $VM_IP:$REMOTE_DIR"
    rsync -az --delete \
        --exclude='.git' \
        --exclude='.venv' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='builddir' \
        --exclude='overlay/build' \
        --exclude='.mypy_cache' \
        --exclude='.pytest_cache' \
        --exclude='*.egg-info' \
        -e "ssh $SSH_OPTS" \
        "$PROJECT_DIR/" "ubuntu@$VM_IP:$REMOTE_DIR/"
}

do_rebuild() {
    echo "=> rebuild overlay + reinstall python"
    ssh_run "cd $REMOTE_DIR && \
        ([ -d builddir ] || meson setup builddir --prefix=\$HOME/.local) && \
        ninja -C builddir && \
        install -m755 builddir/overlay/aside-overlay ~/.local/bin/aside-overlay && \
        ~/.local/lib/aside/venv/bin/pip install . -q" 2>&1
}

do_build_overlay() {
    echo "=> build overlay only"
    ssh_run "cd $REMOTE_DIR && \
        ([ -d builddir ] || meson setup builddir --prefix=\$HOME/.local) && \
        ninja -C builddir && \
        install -m755 builddir/overlay/aside-overlay ~/.local/bin/aside-overlay" 2>&1
}

do_install_python() {
    echo "=> reinstall python package only"
    ssh_run "cd $REMOTE_DIR && \
        ~/.local/lib/aside/venv/bin/pip install . -q" 2>&1
}

do_restart() {
    echo "=> restart services"
    ssh_run "systemctl --user restart aside-daemon aside-overlay && sleep 3" 2>&1
    echo "=> services restarted"
}

do_query() {
    local query="$1"
    echo "=> testing query: $query"
    ssh_run "\$HOME/.local/bin/aside query '$query'" 2>&1
    # Wait for response, then show it
    sleep 3
    local last_id
    last_id=$(ssh_run "\$HOME/.local/bin/aside ls 2>/dev/null | head -1 | awk '{print \$1}'")
    if [ -n "$last_id" ]; then
        echo "=> response:"
        ssh_run "\$HOME/.local/bin/aside show $last_id" 2>&1
    fi
}

do_ssh() {
    ssh_run "$@"
}

do_logs() {
    echo "=== daemon log ==="
    ssh_run "journalctl --user -u aside-daemon -n 30 --no-pager" 2>&1 || true
    echo ""
    echo "=== overlay log ==="
    ssh_run "journalctl --user -u aside-overlay -n 30 --no-pager" 2>&1 || true
}

do_status() {
    echo "=== service status ==="
    ssh_run "systemctl --user status aside-daemon aside-overlay --no-pager" 2>&1 || true
}

# --- parse args ---------------------------------------------------------------

ACTION="full"
QUERY=""
SSH_ARGS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --setup)        ACTION="setup"; shift ;;
        --overlay-only) ACTION="overlay"; shift ;;
        --python-only)  ACTION="python"; shift ;;
        --restart-only) ACTION="restart"; shift ;;
        --query)        QUERY="$2"; shift 2 ;;
        --logs)         ACTION="logs"; shift ;;
        --status)       ACTION="status"; shift ;;
        --ssh)          ACTION="ssh"; shift; SSH_ARGS="$*"; break ;;
        -h|--help)
            cat <<'HELP'
Usage: dev/vm-sync.sh [OPTIONS]

First-time:
  --setup          Run exact README install commands (apt + clone + make install)

Iteration (rsync-based, no git needed):
  (no flags)       rsync + make install + restart services
  --overlay-only   rsync + rebuild C overlay only + restart
  --python-only    rsync + reinstall Python package only + restart
  --restart-only   Just restart services

Testing:
  --query TEXT     After sync+rebuild, run a test query
  --logs           Show daemon/overlay journal logs
  --status         Show service status

Utility:
  --ssh CMD        Run arbitrary SSH command in VM
HELP
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- execute ------------------------------------------------------------------

case "$ACTION" in
    setup)
        do_setup
        ;;
    overlay)
        do_rsync
        do_build_overlay
        do_restart
        ;;
    python)
        do_rsync
        do_install_python
        do_restart
        ;;
    restart)
        do_restart
        ;;
    logs)
        do_logs
        ;;
    status)
        do_status
        ;;
    ssh)
        do_ssh "$SSH_ARGS"
        ;;
    full)
        do_rsync
        do_sync_env
        do_rebuild
        do_restart
        ;;
esac

if [[ -n "$QUERY" ]]; then
    do_query "$QUERY"
fi

echo "=> done"
