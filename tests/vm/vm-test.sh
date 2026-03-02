#!/bin/bash
# Sync local aside tree to a vmt VM and run setup.
# Usage: ./tests/vm/vm-test.sh [VM_NAME]
#   VM_NAME defaults to arch-sway.
#
# Copies the working tree (uncommitted changes included) to ~/aside in
# the VM, then runs the setup script. No git push required.
set -euo pipefail

VM="${1:-arch-sway}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VMT_KEY="$HOME/.local/share/vmt/id_ed25519"
SSH_OPTS="-i $VMT_KEY -o StrictHostKeyChecking=no"

# Source .env for API keys if present
if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    source "$REPO_ROOT/.env"
    set +a
fi

# Resolve VM IP
VM_IP=$(virsh -c qemu:///system domifaddr "vmt-$VM" \
    | awk '/ipv4/{print $4}' | cut -d/ -f1)
if [ -z "$VM_IP" ]; then
    echo "Error: could not resolve IP for $VM" >&2
    exit 1
fi
VM_USER="arch"

echo "=== Syncing local tree to $VM ($VM_IP) ==="
TARBALL=$(mktemp /tmp/aside-sync.XXXXXX.tar.gz)
tar czf "$TARBALL" -C "$REPO_ROOT" \
    --exclude=.venv \
    --exclude=builddir \
    --exclude=.git \
    --exclude=.env \
    --exclude='*.egg-info' \
    --exclude=__pycache__ \
    --exclude='dist/' \
    .
scp $SSH_OPTS "$TARBALL" "$VM_USER@$VM_IP:/tmp/aside-sync.tar.gz"
rm -f "$TARBALL"
vmt ssh "$VM" -- "rm -rf ~/aside && mkdir ~/aside && tar xzf /tmp/aside-sync.tar.gz -C ~/aside && rm /tmp/aside-sync.tar.gz"

# Inject API key from host env
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "=== Injecting API key ==="
    vmt ssh "$VM" -- "mkdir -p ~/.config/aside && echo ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY > ~/.config/aside/env"
fi

echo "=== Running setup ==="
vmt ssh "$VM" -- "bash ~/aside/tests/vm/setup-arch.sh"

echo "=== Opening SPICE viewer ==="
vmt view "$VM"
