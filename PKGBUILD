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
    'python-litellm'
    'wayland'
    'cairo'
    'pango'
    'json-c'
)
makedepends=(
    'meson'
    'ninja'
    'python-setuptools'
    'python-build'
    'python-installer'
    'python-wheel'
    'wayland-protocols'
)
optdepends=(
    'python-kokoro: text-to-speech support'
    'python-sounddevice: TTS audio output'
    'python-soundfile: TTS audio file handling'
    'python-faster-whisper: speech-to-text'
    'python-webrtcvad-wheels: voice activity detection'
    'python-gobject: GTK4 input window'
    'gtk4: GTK4 input window'
    'grim: screenshot plugin'
    'slurp: screenshot region selection'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/v$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    cd "$srcdir/$pkgname-$pkgver"

    # Build C overlay
    cd overlay
    meson setup build --prefix=/usr
    ninja -C build
    cd ..

    # Build Python package
    python -m build --wheel --no-isolation
}

package() {
    cd "$srcdir/$pkgname-$pkgver"

    # Install C overlay
    DESTDIR="$pkgdir" ninja -C overlay/build install

    # Install Python package
    python -m installer --destdir="$pkgdir" dist/*.whl

    # Wrapper scripts
    install -d "$pkgdir/usr/bin"

    cat > "$pkgdir/usr/bin/aside" << 'WRAPPER'
#!/bin/sh
exec python3 -m aside.cli "$@"
WRAPPER
    chmod 755 "$pkgdir/usr/bin/aside"

    cat > "$pkgdir/usr/bin/aside-input" << 'WRAPPER'
#!/bin/sh
exec python3 -m aside.input.window "$@"
WRAPPER
    chmod 755 "$pkgdir/usr/bin/aside-input"

    cat > "$pkgdir/usr/bin/aside-status" << 'WRAPPER'
#!/bin/sh
exec python3 -m aside.status "$@"
WRAPPER
    chmod 755 "$pkgdir/usr/bin/aside-status"

    # Systemd units (patch paths for system-wide install)
    install -Dm644 data/aside-daemon.service "$pkgdir/usr/lib/systemd/user/aside-daemon.service"
    sed -i 's|%h/.local/lib/aside/venv/bin/python3|/usr/bin/python3|' \
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
