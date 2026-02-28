PREFIX   ?= $(HOME)/.local
PYTHON   ?= python3
VENV     := $(PREFIX)/lib/aside/venv
BIN      := $(PREFIX)/bin
LIB      := $(PREFIX)/lib/aside
SYSTEMD  := $(HOME)/.config/systemd/user
APPS     := $(HOME)/.local/share/applications
CONFIG   := $(HOME)/.config/aside

.PHONY: all overlay install dev install-extras-tts install-extras-voice install-extras-gtk uninstall clean

all: overlay

# ---------------------------------------------------------------------------
# Build the C overlay
# ---------------------------------------------------------------------------
overlay:
	cd overlay && meson setup build --prefix=$(PREFIX) --reconfigure 2>/dev/null || cd overlay && meson setup build --prefix=$(PREFIX)
	ninja -C overlay/build

# ---------------------------------------------------------------------------
# Fast dev reinstall — reuses existing venv, restarts services
# ---------------------------------------------------------------------------
dev: overlay
	$(VENV)/bin/pip install ".[gtk]"
	install -Dm755 overlay/build/aside-overlay $(BIN)/aside-overlay
	@install -d $(BIN)
	@for cmd in aside aside-input aside-status aside-actions; do \
		src="$(VENV)/bin/$$cmd"; \
		if [ -f "$$src" ]; then \
			ln -sf "$$src" "$(BIN)/$$cmd"; \
		fi; \
	done
	cp -a plugins/* $(LIB)/plugins/ 2>/dev/null || true
	install -Dm644 data/aside-daemon.service $(SYSTEMD)/aside-daemon.service
	install -Dm644 data/aside-overlay.service $(SYSTEMD)/aside-overlay.service
	systemctl --user daemon-reload
	systemctl --user restart aside-daemon aside-overlay
	@echo "==> Dev reinstall done"

# ---------------------------------------------------------------------------
# Install everything
# ---------------------------------------------------------------------------
install: overlay
	@echo "==> Creating venv at $(VENV)"
	$(PYTHON) -m venv $(VENV) --clear
	$(VENV)/bin/pip install --upgrade pip setuptools
	$(VENV)/bin/pip install ".[gtk]"
	@echo "==> Installing overlay binary"
	install -Dm755 overlay/build/aside-overlay $(BIN)/aside-overlay
	@echo "==> Installing wrapper scripts"
	install -d $(BIN)
	printf '#!/bin/sh\nexec $(VENV)/bin/python3 -m aside.cli "$$@"\n' > $(BIN)/aside
	chmod 755 $(BIN)/aside
	printf '#!/bin/sh\nexec $(VENV)/bin/python3 -m aside.input.window "$$@"\n' > $(BIN)/aside-input
	chmod 755 $(BIN)/aside-input
	printf '#!/bin/sh\nexec $(VENV)/bin/python3 -m aside.status "$$@"\n' > $(BIN)/aside-status
	chmod 755 $(BIN)/aside-status
	printf '#!/bin/sh\nexec $(VENV)/bin/python3 -m aside.actions.window "$$@"\n' > $(BIN)/aside-actions
	chmod 755 $(BIN)/aside-actions
	@echo "==> Installing systemd units"
	install -Dm644 data/aside-daemon.service $(SYSTEMD)/aside-daemon.service
	install -Dm644 data/aside-overlay.service $(SYSTEMD)/aside-overlay.service
	@echo "==> Installing desktop entry"
	install -Dm644 data/aside.desktop $(APPS)/aside.desktop
	@echo "==> Installing example config"
	install -d $(CONFIG)
	@if [ ! -f $(CONFIG)/config.toml ]; then \
		install -Dm644 data/config.toml.example $(CONFIG)/config.toml; \
		echo "    Installed example config to $(CONFIG)/config.toml"; \
	else \
		echo "    Config already exists — not overwriting"; \
	fi
	@echo "==> Installing plugins"
	install -d $(LIB)/plugins
	cp -a plugins/* $(LIB)/plugins/ 2>/dev/null || true
	@echo "==> Installing waybar module config"
	install -d $(HOME)/.config/waybar
	install -Dm644 data/waybar/aside.json $(HOME)/.config/waybar/aside.json
	systemctl --user daemon-reload
	@echo "==> Done. Enable with:"
	@echo "    systemctl --user enable --now aside-daemon aside-overlay"

# ---------------------------------------------------------------------------
# Optional extras
# ---------------------------------------------------------------------------
install-extras-tts:
	$(VENV)/bin/pip install ".[tts]"

install-extras-voice:
	$(VENV)/bin/pip install ".[voice]"

install-extras-gtk:
	$(VENV)/bin/pip install ".[gtk]"

# ---------------------------------------------------------------------------
# Uninstall (preserves config)
# ---------------------------------------------------------------------------
uninstall:
	systemctl --user disable --now aside-daemon aside-overlay 2>/dev/null || true
	rm -f $(BIN)/aside $(BIN)/aside-input $(BIN)/aside-status $(BIN)/aside-overlay
	rm -rf $(LIB)
	rm -f $(SYSTEMD)/aside-daemon.service $(SYSTEMD)/aside-overlay.service
	rm -f $(APPS)/aside.desktop
	systemctl --user daemon-reload
	@echo "==> Uninstalled (config preserved at $(CONFIG))"

# ---------------------------------------------------------------------------
# Clean build artifacts
# ---------------------------------------------------------------------------
clean:
	rm -rf overlay/build
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
