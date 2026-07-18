#!/usr/bin/env bash
# Record a feature demo from the test VM's framebuffer, cut it into a GIF,
# and attach it to a PR — fully headless (no SPICE viewer, no windows).
#
# Usage:
#   dev/vm-demo.sh <pr-number> <gif-name> <demo-script>
#
#   pr-number    GitHub PR to attach the demo to (must exist)
#   gif-name     basename for the GIF (e.g. "aside-move" -> aside-move.gif)
#   demo-script  bash file sourced during capture; helpers in scope:
#                  snd '<json>'   send a raw command to the overlay socket
#                  cli '<args>'   run `aside <args>` on the VM
#                Use sleeps between steps — capture runs at ~4-6 fps.
#
# Requirements:
#   - VM booted (`vmt up aside-ubuntu-kde`) with aside installed (vm-sync.sh)
#   - The VM compositor must render on the seat (NOT --virtual/headless),
#     or the framebuffer shows a TTY. One-time switch on the VM:
#       systemctl --user disable --now test-compositor
#       echo '[ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ] && exec /usr/bin/kwin_wayland --no-lockscreen' > ~/.bash_profile
#       sudo systemctl restart getty@tty1   # then restart aside-overlay
#   - host: ffmpeg, virsh, gh
#
# GIFs are pushed to the orphan `assets` branch under pr-<N>/ and embedded
# into the PR body under a "## Demo" section (created if absent).

set -euo pipefail

PR="${1:?usage: vm-demo.sh <pr-number> <gif-name> <demo-script>}"
NAME="${2:?gif name required}"
DEMO="${3:?demo script required}"
[ -f "$DEMO" ] || { echo "ERROR: demo script '$DEMO' not found" >&2; exit 1; }

VM_NAME="${VM_NAME:-aside-ubuntu-kde}"
DOM="vmt-${VM_NAME}"
VIRSH="virsh -c qemu:///system"
FRAMES="${VM_DEMO_FRAMES:-90}"          # ~20s at the achieved capture rate
CAPTURE_INTERVAL="${VM_DEMO_INTERVAL:-0.12}"

# SSH key discovery — same order as vm-sync.sh / vmt
if [ -n "${VMT_SSH_KEY:-}" ]; then SSH_KEY="$VMT_SSH_KEY"
elif [ -e "$HOME/.local/share/vmt/id_ed25519" ]; then SSH_KEY="$HOME/.local/share/vmt/id_ed25519"
else SSH_KEY="$HOME/.ssh/id_ed25519_vmt"; fi

VM_IP=$($VIRSH domifaddr "$DOM" 2>/dev/null | awk '/ipv4/ {sub(/\/.*/,"",$4); print $4; exit}')
[ -n "$VM_IP" ] || { echo "ERROR: VM '$DOM' not running or no IP" >&2; exit 1; }
SSH="ssh -o StrictHostKeyChecking=no -o LogLevel=ERROR -i $SSH_KEY ubuntu@$VM_IP"

snd() { $SSH "printf '%s\n' '$1' | socat - UNIX-CONNECT:/run/user/1000/aside-overlay.sock"; }
cli() { $SSH "~/.local/bin/aside $1"; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/frames"

echo "=> Capturing (${FRAMES} frames) while running $DEMO"
( i=0; while [ "$i" -lt "$FRAMES" ]; do
    $VIRSH screenshot "$DOM" "$WORK/frames/$(printf 'f%04d' "$i").png" >/dev/null 2>&1
    i=$((i+1)); sleep "$CAPTURE_INTERVAL"
  done ) &
CAP=$!
# shellcheck disable=SC1090
source "$DEMO"
kill "$CAP" 2>/dev/null || true; wait "$CAP" 2>/dev/null || true
echo "=> $(ls "$WORK/frames" | wc -l) frames captured"

echo "=> Assembling ${NAME}.gif"
ffmpeg -y -loglevel error -framerate 4 -i "$WORK/frames/f%04d.png" \
  -vf "fps=4,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer" \
  "$WORK/${NAME}.gif"

echo "=> Publishing to assets branch"
URL=$(git remote get-url origin)
PUB="$WORK/publish"
if git ls-remote --exit-code --heads "$URL" assets >/dev/null 2>&1; then
    git clone -q --depth 1 --branch assets "$URL" "$PUB"
else
    mkdir -p "$PUB" && (cd "$PUB" && git init -q -b assets && git remote add origin "$URL")
fi
mkdir -p "$PUB/pr-$PR"
cp "$WORK/${NAME}.gif" "$PUB/pr-$PR/"
(cd "$PUB" && git add -A && git commit -q -m "assets: PR #$PR demo ${NAME}.gif" && git push -q origin assets)

RAW_URL="https://raw.githubusercontent.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/assets/pr-$PR/${NAME}.gif"
echo "=> Embedding in PR #$PR"
BODY=$(gh pr view "$PR" --json body -q .body)
if ! grep -q '^## Demo' <<<"$BODY"; then
    BODY="$BODY

## Demo

Recorded headlessly on the test VM (framebuffer capture during verification):"
fi
gh pr edit "$PR" --body "$BODY

![${NAME}](${RAW_URL})" >/dev/null

echo "=> Done: $RAW_URL"
