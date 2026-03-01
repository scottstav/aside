# Maintainer: Scott Stavropoulos <scottstav@gmail.com>
pkgname=aside
pkgver=0.1.0
pkgrel=1
pkgdesc="Wayland-native LLM desktop assistant"
arch=('x86_64')
url="https://github.com/scottstav/aside"
license=('MIT')
depends=(
    'python>=3.11'
    'wayland'
    'cairo'
    'pango'
    'json-c'
    'pipewire'
)
makedepends=(
    'meson'
    'ninja'
    'python-pip'
    'python-setuptools'
    'python-build'
    'python-wheel'
    'wayland-protocols'
)
optdepends=(
    'grim: screenshot plugin'
    'slurp: screenshot region selection'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/v$pkgver.tar.gz")
sha256sums=('SKIP')

_venv=/opt/aside/venv

build() {
    cd "$srcdir/$pkgname-$pkgver"

    # Build C overlay
    cd overlay
    meson setup build --prefix=/usr
    ninja -C build
    cd ..

    # Build Python venv with all deps
    python -m venv "$srcdir/venv"
    "$srcdir/venv/bin/pip" install --upgrade pip setuptools
    "$srcdir/venv/bin/pip" install ".[gtk,voice]"
    "$srcdir/venv/bin/pip" install ".[tts]" || echo "Note: TTS extras not available for Python $(python --version)"
}

package() {
    cd "$srcdir/$pkgname-$pkgver"

    # Install C overlay
    DESTDIR="$pkgdir" ninja -C overlay/build install

    # Install bundled venv
    install -d "$pkgdir$(dirname $_venv)"
    cp -a "$srcdir/venv" "$pkgdir$_venv"

    # Fix venv shebang paths (they point to $srcdir during build)
    find "$pkgdir$_venv/bin" -type f -exec \
        sed -i "s|$srcdir/venv|$_venv|g" {} +

    # Fix the pyvenv.cfg home path
    sed -i "s|$srcdir/venv|$_venv|g" "$pkgdir$_venv/pyvenv.cfg"

    # Wrapper scripts
    install -d "$pkgdir/usr/bin"

    for cmd in aside aside-input aside-status aside-actions; do
        cat > "$pkgdir/usr/bin/$cmd" << WRAPPER
#!/bin/sh
exec $_venv/bin/$cmd "\$@"
WRAPPER
        chmod 755 "$pkgdir/usr/bin/$cmd"
    done

    # Systemd units (patch paths for system-wide install)
    install -Dm644 data/aside-daemon.service "$pkgdir/usr/lib/systemd/user/aside-daemon.service"
    sed -i "s|%h/.local/lib/aside/venv/bin/python3 -m aside.daemon|$_venv/bin/python3 -m aside.daemon|" \
        "$pkgdir/usr/lib/systemd/user/aside-daemon.service"
    install -Dm644 data/aside-overlay.service "$pkgdir/usr/lib/systemd/user/aside-overlay.service"
    sed -i 's|%h/.local/bin/aside-overlay|/usr/bin/aside-overlay|' \
        "$pkgdir/usr/lib/systemd/user/aside-overlay.service"

    # Desktop entry
    install -Dm644 data/aside.desktop "$pkgdir/usr/share/applications/aside.desktop"

    # Example config
    install -Dm644 data/config.toml.example "$pkgdir/usr/share/aside/config.toml.example"

    # Plugins
    install -d "$pkgdir/usr/share/aside/plugins"
    install -Dm644 plugins/*.py "$pkgdir/usr/share/aside/plugins/"

    # Waybar module
    install -Dm644 data/waybar/aside.json "$pkgdir/usr/share/aside/waybar/aside.json"

    # License
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
