#!/usr/bin/env bash
# Rebuild the aside-ubuntu-kde golden snapshot from scratch (one-time / recovery).
#
# The daily dev loop does NOT use this — it restores the snapshot in seconds:
#   cd ~/projects/vmt && source .venv/bin/activate
#   vmt restore aside-ubuntu-kde golden
#   virsh -c qemu:///system start vmt-aside-ubuntu-kde   # never `vmt up` (recreates disk, destroys snapshot)
#   dev/vm-sync.sh
#
# This script: full provision -> aside setup -> compositor-on-seat -> snapshot.
set -euo pipefail

VM=aside-ubuntu-kde
DOM=vmt-$VM
V="virsh -c qemu:///system"
ASIDE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd ~/projects/vmt && source .venv/bin/activate
vmt destroy $VM >/dev/null 2>&1 || true
$V snapshot-delete $DOM golden --metadata >/dev/null 2>&1 || true
rm -f ~/.cache/vmt/vms/$VM/disk.qcow2 ~/.cache/vmt/vms/$VM/seed.iso
vmt up $VM

IP=$($V domifaddr $DOM | awk '/ipv4/ {sub(/\/.*/,"",$4); print $4; exit}')
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -i $HOME/.ssh/id_ed25519_vmt ubuntu@$IP"
echo "=> waiting for cloud-init"
$SSH "cloud-init status --wait >/dev/null 2>&1; cloud-init status"

echo "=> aside setup"
cd "$ASIDE_DIR" && VM_NAME=$VM dev/vm-sync.sh --setup

echo "=> compositor on seat + overlay env"
$SSH 'bash -s' <<'EOF'
set -u
systemctl --user disable --now test-compositor 2>/dev/null
printf '[ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ] && exec /usr/bin/kwin_wayland --no-lockscreen >~/kwin.log 2>&1\n' > ~/.bash_profile
mkdir -p ~/.config/systemd/user/aside-overlay.service.d
printf '[Service]\nEnvironment=ASIDE_DEBUG=1\nEnvironment=WAYLAND_DISPLAY=wayland-0\n' > ~/.config/systemd/user/aside-overlay.service.d/debug.conf
systemctl --user daemon-reload
sudo systemctl restart getty@tty1; sleep 8
pgrep kwin_wayland >/dev/null && echo KWIN_OK
EOF

echo "=> snapshot"
$SSH 'sudo shutdown now' 2>/dev/null || true
until [ "$($V domstate $DOM)" = "shut off" ]; do sleep 5; done
cd ~/projects/vmt && vmt snapshot $VM golden
qemu-img snapshot -l ~/.cache/vmt/vms/$VM/disk.qcow2 | tail -1
echo "=> golden ready"
