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
    'python-build'
    'python-installer'
    'python-wheel'
    'python-meson-python'
    'wayland-protocols'
)
optdepends=(
    'grim: screenshot plugin'
    'slurp: screenshot region selection'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/v$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    cd "$srcdir/$pkgname-$pkgver"
    python -m build --wheel --no-isolation .
}

package() {
    cd "$srcdir/$pkgname-$pkgver"
    python -m installer --destdir="$pkgdir" dist/aside_assistant-*.whl

    # Systemd units
    install -Dm644 data/aside-daemon.service "$pkgdir/usr/lib/systemd/user/aside-daemon.service"
    install -Dm644 data/aside-overlay.service "$pkgdir/usr/lib/systemd/user/aside-overlay.service"

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
