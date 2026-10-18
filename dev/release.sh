#!/usr/bin/env bash
# Cut an aside release: GitHub tag + release, the AUR package, and this machine.
#
#   dev/release.sh            # patch bump (0.8.1 -> 0.8.2)
#   dev/release.sh 0.9.0      # explicit version
#   dev/release.sh --check    # run the gate only, publish nothing
#   make release [V=0.9.0] [NOTES=notes.md]
#
# NOTES: first line is the release title (shown after "vX.Y.Z: "), the rest
# is the body. Without it the notes are the commit subjects since last tag.
#
# Nothing public happens until the code passes the test suite and a live
# query through aside's own streaming code (dev/smoke.py), both against the
# litellm the PKGBUILD pins. The unit tests mock litellm.completion, so the
# live query is the only check that a litellm version actually works. If the
# API refuses the account itself (no key, bad key, spend limit) it is skipped
# with a warning, unless the litellm pin changed since the last release: a
# new litellm never ships without a real query passing.
#
# Order: preflight, gate, tag + GitHub release, build the real package from
# the GitHub tarball, smoke the built package, install it here (one pkexec
# prompt), then the PKGBUILD/.SRCINFO commit and the AUR push. Any failure
# before the AUR push leaves the AUR and this machine untouched.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -z "${NOTES:-}" ] || NOTES=$(realpath -m -- "$NOTES")
cd "$REPO"

check_only=0
if [ "${1:-}" = "--check" ]; then
    check_only=1
    shift
fi

published=0  # flips once the tag is pushed

step() { printf '\n==> %s\n' "$*"; }
die() {
    printf '\n==> FAILED: %s\n' "$*" >&2
    if [ "$published" = 0 ]; then
        echo "    Nothing was published." >&2
    else
        echo "    $tag is tagged on GitHub, but the AUR and this machine are untouched." >&2
        echo "    Fix it, then release the next patch version." >&2
    fi
    exit 1
}
trap 'die "unexpected failure at line $LINENO: $BASH_COMMAND"' ERR
smoke() {  # smoke <python> <smoke.py> <failure message>
    local rc=0
    "$1" "$2" || rc=$?
    case $rc in
        0) ;;
        2) [ "$pin_changed" = 0 ] || die "$litellm_req is new since $prev and the live query couldn't run (the API refused this account). A litellm change only ships after a real query passes."
           echo "    live query skipped: the API refused this account, not the code" ;;
        *) die "$3" ;;
    esac
}
pyver() { "$1" -c 'import importlib.metadata as m; print(m.version("litellm"))'; }

# ── version ────────────────────────────────────────────────────────────────
current=$(sed -nE 's/^version = "([^"]+)"/\1/p' pyproject.toml)
[ -n "$current" ] || die "can't read the version from pyproject.toml"
if [ -n "${1:-}" ]; then
    version="${1#v}"
else
    IFS=. read -r major minor patch <<<"$current"
    version="$major.$minor.$((patch + 1))"
fi
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "bad version: $version"
tag="v$version"

# ── preflight ──────────────────────────────────────────────────────────────
step "Preflight: $current -> $version"
[ "$(git rev-parse --abbrev-ref HEAD)" = master ] || die "not on master"
git diff --quiet && git diff --cached --quiet || die "uncommitted changes"
git fetch -q origin master
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)" ] \
    || die "master and origin/master differ (pull or push first)"
! git rev-parse -q --verify "refs/tags/$tag" >/dev/null || die "$tag already exists locally"
! git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null || die "$tag already exists on GitHub"
prev=$(git describe --tags --abbrev=0)
[ -n "$(git rev-list "$prev..HEAD")" ] || die "nothing to release since $prev"
[ -z "${NOTES:-}" ] || [ -s "$NOTES" ] || die "NOTES file missing or empty: $NOTES"
litellm_req=$(grep -m1 -oE 'litellm==[0-9][0-9.]*' PKGBUILD) \
    || die "PKGBUILD must pin litellm (litellm==X.Y.Z)"
py_req=$(grep -m1 -oE 'litellm==[0-9][0-9.]*' pyproject.toml) \
    || die "pyproject.toml must pin litellm too, or make install gets whatever is newest"
[ "$py_req" = "$litellm_req" ] || die "litellm pins differ: PKGBUILD $litellm_req, pyproject.toml $py_req"
prev_req=$(git show "$prev:PKGBUILD" | grep -m1 -oE 'litellm==[0-9][0-9.]*' || echo "unpinned litellm")
pin_changed=0
[ "$litellm_req" = "$prev_req" ] || pin_changed=1
echo "    $litellm_req$([ "$pin_changed" = 1 ] && echo " (was $prev_req in $prev)")"
missing=$(pacman -T python-build python-wheel python-setuptools || true)
[ -z "$missing" ] || die "missing makedepends: $missing"
gh auth status >/dev/null 2>&1 || die "gh is not logged in"
aur_repos=$(ssh -o BatchMode=yes -o ConnectTimeout=10 aur@aur.archlinux.org list-repos 2>/dev/null) \
    || die "can't reach the AUR over ssh"
grep -qE '^\s*aside$' <<<"$aur_repos" || die "this AUR account doesn't maintain aside"
pgrep -f polkit-gnome-authentication-agent-1 >/dev/null \
    || die "polkit agent isn't running (the install step needs its pkexec prompt)"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/aside-release.XXXXXX")
trap 'rc=$?; if [ $rc -eq 0 ]; then rm -rf "$tmp"; else echo "    build files kept in $tmp" >&2; fi' EXIT

# ── gate: tests + live query, before anything is public ───────────────────
step "Gate: test suite and a live query against the litellm that will ship"
mkdir -p "$tmp/src"
git archive HEAD | tar -x -C "$tmp/src"
python3 -m venv --system-site-packages "$tmp/venv"
pip=("$tmp/venv/bin/pip" install -q --disable-pip-version-check)
# Same install as the PKGBUILD's build(): aside without deps, then the
# pinned litellm and mistune.
"${pip[@]}" --no-deps "$tmp/src"
"${pip[@]}" "$litellm_req" mistune pytest
gate_litellm=$(pyver "$tmp/venv/bin/python")
echo "    litellm $gate_litellm"
# The socket tests bind under pytest's tmp dir, and AF_UNIX paths cap at
# 108 bytes, so keep it short whatever TMPDIR the caller has.
(cd "$tmp/src" && TMPDIR=/tmp "$tmp/venv/bin/python" -m pytest tests -q -p no:cacheprovider) \
    || die "test suite failed"
smoke "$tmp/venv/bin/python" "$tmp/src/dev/smoke.py" "live smoke query failed"

if [ "$check_only" = 1 ]; then
    step "Gate passed. $tag is ready; run without --check to release it."
    exit 0
fi

# ── tag + GitHub release ───────────────────────────────────────────────────
step "Tag $tag and publish the GitHub release"
sed -i -E "s/^version = \"[^\"]+\"/version = \"$version\"/" pyproject.toml
sed -i -E "s/^pkgver=.*/pkgver=$version/; s/^pkgrel=.*/pkgrel=1/" PKGBUILD
git commit -qam "release: $tag"
git tag "$tag"
git push -q origin master "$tag"
published=1
if [ -n "${NOTES:-}" ]; then
    title="$tag: $(head -1 "$NOTES")"
    notes=$(tail -n +2 "$NOTES" | sed '/./,$!d')
else
    title="$tag"
    notes=$(git log --no-merges --format='- %s' "$prev..$tag~1" \
        | grep -vE '^- (release|build)(\(|:)' || true)
fi
gh release create "$tag" --title "$title" --notes "${notes:-Maintenance release.}" >/dev/null

# ── checksum + build exactly what the AUR will build ──────────────────────
step "Build the package from the GitHub tarball"
mkdir -p "$tmp/pkg" "$tmp/build" "$tmp/out"
tarball="$tmp/pkg/aside-$version.tar.gz"
# codeload can lag a freshly pushed tag
curl -sfL --retry 8 --retry-delay 5 --retry-all-errors -o "$tarball" \
    "https://github.com/scottstav/aside/archive/$tag.tar.gz" || die "couldn't download the $tag tarball"
sha=$(sha256sum "$tarball" | cut -d' ' -f1)
sed -i -E "s/^sha256sums=.*/sha256sums=('$sha')/" PKGBUILD
makepkg --printsrcinfo > .SRCINFO
cp PKGBUILD "$tmp/pkg/"
mkpkg() { (cd "$tmp/pkg" && BUILDDIR="$tmp/build" PKGDEST="$tmp/out" SRCDEST="$tmp/pkg" makepkg "$@"); }
mkpkg -f --noconfirm || die "makepkg failed"
pkgfile=$(mkpkg --packagelist | grep -v -- "-debug-" | sed -n 1p)
[ -f "$pkgfile" ] || die "built package not found"

step "Smoke the built package"
venv="$tmp/build/aside/src/venv"
"$venv/bin/python" -c 'import aside.cli, aside.daemon, aside.query' \
    || die "the built package doesn't import"
built_litellm=$(pyver "$venv/bin/python")
if [ "$built_litellm" != "$gate_litellm" ]; then
    # PyPI moved during the release; re-run the suite on what actually ships
    echo "    litellm moved to $built_litellm during the build, re-running tests"
    "$venv/bin/pip" install -q --disable-pip-version-check pytest
    (cd "$tmp/build/aside/src/aside-$version" && TMPDIR=/tmp "$venv/bin/python" -m pytest tests -q -p no:cacheprovider) \
        || die "test suite failed on the built package"
fi
smoke "$venv/bin/python" "$REPO/dev/smoke.py" "live smoke failed on the built package"

# ── install here, then the AUR ─────────────────────────────────────────────
step "Install $tag here (approve the pkexec prompt)"
pkexec pacman -U --noconfirm "$pkgfile" || die "install failed or was cancelled"
systemctl --user restart aside-daemon aside-overlay
systemctl --user is-active -q aside-daemon || die "aside-daemon didn't come back up"
installed=$(pacman -Q aside | cut -d' ' -f2)
[ "$installed" = "$version-1" ] || die "pacman reports aside $installed, expected $version-1"

step "Publish to the AUR"
git commit -qam "build: PKGBUILD sha256 and .SRCINFO for $tag"
git push -q origin master
git clone -q ssh://aur@aur.archlinux.org/aside.git "$tmp/aur"
cp PKGBUILD .SRCINFO "$tmp/aur/"
git -C "$tmp/aur" add PKGBUILD .SRCINFO
git -C "$tmp/aur" -c user.name="$(git config user.name)" -c user.email="$(git config user.email)" \
    commit -qm "update to $tag"
git -C "$tmp/aur" push -q origin HEAD:master || {
    echo "==> FAILED: AUR push. $tag is installed here; retry the push from $tmp/aur" >&2
    trap - EXIT
    exit 1
}

step "Released $tag"
echo "    https://github.com/scottstav/aside/releases/tag/$tag"
echo "    https://aur.archlinux.org/packages/aside"
echo "    installed here: aside $installed (litellm $built_litellm), services restarted"
if [ -L "$HOME/.local/bin/aside" ]; then
    echo "    note: ~/.local/bin/aside is the dev build and shadows this package. 'make system' to run the release."
fi
