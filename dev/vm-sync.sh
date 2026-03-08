#!/usr/bin/env bash
# Fast dev loop for aside on a vmt VM.
#
# --setup installs system deps, rsyncs your LOCAL working tree, and runs
# make install + enables services.  No git clone — you always test what's
# on disk, not what's on master.
#
# After setup, iterate with rsync (no git commit/push needed):
#   dev/vm-sync.sh                    # rsync + pip install + restart
#   dev/vm-sync.sh --python-only      # same (alias)
#   dev/vm-sync.sh --query "hello"    # sync + rebuild + restart + test query
#
# Requires: VM already booted with `vmt up aside-ubuntu-kde`

set -euo pipefail

VM_NAME="${VM_NAME:-aside-ubuntu-kde}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY="$HOME/.local/share/vmt/id_ed25519"
VMT_DIR="$HOME/projects/vmt"

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
    echo "=> [1/6] Fixing KDE autologin"
    ssh_run "sudo systemctl restart getty@tty1" 2>/dev/null || true

    echo "=> [2/6] Installing system dependencies"
    ssh_run "sudo apt-get update -qq && sudo apt-get install -y -qq \
        python3-venv python3-pip python3-dev \
        meson ninja-build valac \
        libgtk-4-dev gobject-introspection libgirepository1.0-dev \
        python3-gi python3-gi-cairo gir1.2-gtk-4.0 git"

    echo "=> [3/6] Building gtk4-layer-shell from source"
    ssh_run "if [ ! -f /usr/local/lib/x86_64-linux-gnu/libgtk4-layer-shell.so ]; then \
        rm -rf /tmp/gtk4-layer-shell && \
        git clone https://github.com/wmww/gtk4-layer-shell.git /tmp/gtk4-layer-shell && \
        cd /tmp/gtk4-layer-shell && meson setup build && ninja -C build && sudo ninja -C build install && \
        sudo ldconfig; \
    else echo '   already installed, skipping'; fi"

    echo "=> [4/6] Syncing local working tree to VM"
    do_rsync
    do_sync_env

    echo "=> [5/6] make install"
    ssh_run "cd $REMOTE_DIR && make install"

    echo "=> [6/6] Enabling and starting services"
    ssh_run "systemctl --user enable --now aside-daemon aside-overlay" 2>&1 || true
    sleep 3

    echo ""
    echo "=> Setup complete. Services running. To iterate: dev/vm-sync.sh"
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
        --exclude='.mypy_cache' \
        --exclude='.pytest_cache' \
        --exclude='*.egg-info' \
        -e "ssh $SSH_OPTS" \
        "$PROJECT_DIR/" "ubuntu@$VM_IP:$REMOTE_DIR/"
}

do_rebuild() {
    # If venv doesn't exist yet, run full make install instead of just pip
    if ! ssh_run "test -f ~/.local/lib/aside/venv/bin/pip" 2>/dev/null; then
        echo "=> venv missing — running make install"
        ssh_run "cd $REMOTE_DIR && make install" 2>&1
    else
        echo "=> reinstall python package"
        ssh_run "cd $REMOTE_DIR && \
            ~/.local/lib/aside/venv/bin/pip install . -q" 2>&1
    fi
    # Always sync data files (desktop entry, systemd units, etc.)
    echo "=> sync data files"
    ssh_run "cd $REMOTE_DIR && \
        cp -f data/aside.desktop ~/.local/share/applications/aside.desktop && \
        cp -f data/aside-daemon.service ~/.config/systemd/user/aside-daemon.service && \
        cp -f data/aside-overlay.service ~/.config/systemd/user/aside-overlay.service && \
        systemctl --user daemon-reload" 2>&1
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
  --setup          Install deps, rsync local code, make install, start services

Iteration (rsync-based, no git needed):
  (no flags)       rsync + pip install + restart services
  --python-only    same as above (alias)
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
    python)
        do_rsync
        do_rebuild
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
