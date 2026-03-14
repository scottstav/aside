PREFIX   ?= $(HOME)/.local
PYTHON   ?= python3
VENV     := $(PREFIX)/lib/aside/venv
BIN      := $(PREFIX)/bin
LIB      := $(PREFIX)/lib/aside
SYSTEMD  := $(HOME)/.config/systemd/user
APPS     := $(HOME)/.local/share/applications
CONFIG   := $(HOME)/.config/aside

.PHONY: all install dev uninstall clean

all: install

# ---------------------------------------------------------------------------
# Fast dev reinstall — pip install into venv, restart services
# ---------------------------------------------------------------------------
dev:
	$(VENV)/bin/pip install --quiet .
	systemctl --user restart aside-daemon aside-overlay
	@echo "==> Dev reinstall done"

# ---------------------------------------------------------------------------
# Full install
# ---------------------------------------------------------------------------
install:
	@echo "==> Creating venv at $(VENV)"
	$(PYTHON) -m venv $(VENV) --clear --system-site-packages
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install .
	@echo "==> Installing wrapper symlinks"
	install -d $(BIN)
	@for cmd in aside aside-overlay aside-status; do \
		src="$(VENV)/bin/$$cmd"; \
		if [ -f "$$src" ]; then \
			ln -sf "$$src" "$(BIN)/$$cmd"; \
		fi; \
	done
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
	systemctl --user daemon-reload
	@echo "==> Done. Enable with:"
	@echo "    systemctl --user enable --now aside-daemon aside-overlay"

# ---------------------------------------------------------------------------
# Uninstall (preserves config)
# ---------------------------------------------------------------------------
uninstall:
	systemctl --user disable --now aside-daemon aside-overlay 2>/dev/null || true
	rm -f $(BIN)/aside $(BIN)/aside-overlay $(BIN)/aside-status
	rm -rf $(LIB) 2>/dev/null; \
	if [ -d "$(LIB)" ]; then \
		echo "Warning: $(LIB) has root-owned files (from sudo aside enable-stt/tts)."; \
		echo "Run manually: sudo rm -rf $(LIB)"; \
	fi
	rm -f $(SYSTEMD)/aside-daemon.service $(SYSTEMD)/aside-overlay.service
	rm -f $(APPS)/aside.desktop
	systemctl --user daemon-reload
	@echo "==> Uninstalled (config preserved at $(CONFIG))"

# ---------------------------------------------------------------------------
# Clean build artifacts
# ---------------------------------------------------------------------------
clean:
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
