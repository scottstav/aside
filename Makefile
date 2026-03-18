PYTHON   ?= python3
VENV     := .venv
BIN      := $(HOME)/.local/bin
SYSTEMD  := $(HOME)/.config/systemd/user
APPS     := $(HOME)/.local/share/applications
CONFIG   := $(HOME)/.config/aside

.PHONY: all install dev system uninstall clean

all: install

# ---------------------------------------------------------------------------
# Dev mode — editable install, shadowing AUR. First run sets up the venv
# and symlinks; subsequent runs just restart services.
# ---------------------------------------------------------------------------
dev:
	@if [ ! -d "$(VENV)" ] || ! grep -q "include-system-site-packages = true" "$(VENV)/pyvenv.cfg" 2>/dev/null; then \
		echo "==> Creating venv"; \
		$(PYTHON) -m venv $(VENV) --clear --system-site-packages; \
		echo "==> Installing editable build"; \
		$(VENV)/bin/pip install -q -e .; \
	fi
	@if [ ! -L "$(BIN)/aside" ] || [ "$$(readlink $(BIN)/aside)" != "$(CURDIR)/$(VENV)/bin/aside" ]; then \
		echo "==> Linking local build"; \
		mkdir -p $(BIN) $(SYSTEMD); \
		ln -sf $(CURDIR)/$(VENV)/bin/aside $(BIN)/aside; \
		ln -sf $(CURDIR)/$(VENV)/bin/aside-overlay $(BIN)/aside-overlay; \
		cp data/aside-daemon.service $(SYSTEMD)/; \
		cp data/aside-overlay.service $(SYSTEMD)/; \
		systemctl --user daemon-reload; \
	fi
	systemctl --user restart aside-daemon aside-overlay
	@echo "==> Dev ready"

# ---------------------------------------------------------------------------
# Switch back to system (AUR) package
# ---------------------------------------------------------------------------
system:
	rm -f $(BIN)/aside $(BIN)/aside-overlay
	rm -f $(SYSTEMD)/aside-daemon.service $(SYSTEMD)/aside-overlay.service
	systemctl --user daemon-reload
	systemctl --user restart aside-daemon aside-overlay
	@echo "==> Switched to AUR build"

# ---------------------------------------------------------------------------
# Full install (non-AUR machines, VMs, etc.)
# ---------------------------------------------------------------------------
install:
	@echo "==> Creating venv at $(VENV)"
	$(PYTHON) -m venv $(VENV) --clear --system-site-packages
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install .
	@echo "==> Installing wrapper symlinks"
	install -d $(BIN)
	@for cmd in aside aside-overlay; do \
		src="$(CURDIR)/$(VENV)/bin/$$cmd"; \
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
	rm -f $(BIN)/aside $(BIN)/aside-overlay
	rm -rf $(VENV)
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
