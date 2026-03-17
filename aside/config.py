"""Configuration system — TOML loading, defaults, and XDG path resolution."""

from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Default configuration — every key the application understands.
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "model": {
        "name": "anthropic/claude-sonnet-4-6",
        "system_prompt": "",
        "timeout": 30,
    },
    "input": {
        "font": "",
    },
    "voice": {
        "enabled": False,
        "stt_model": "base",
        "stt_device": "cpu",
        "smart_silence": True,
        "silence_timeout": 2.5,
        "no_speech_timeout": 3.0,
        "force_send_phrases": ["send it", "that's it"],
    },
    "tts": {
        "enabled": False,
        "model": "",
        "speed": 1.0,
    },
    "overlay": {
        "font": "Sans 13",
        "width": 600,
        "max_lines": 5,
        "position": "top-center",
        "margin_top": 10,
        "margin_right": 0,
        "margin_bottom": 0,
        "margin_left": 0,
        "padding_x": 20,
        "padding_y": 16,
        "corner_radius": 12,
        "border_width": 2,
        "accent_height": 3,
        "scroll_duration": 200,
        "fade_duration": 400,
        "colors": {
            "background": "#1a1b26e6",
            "foreground": "#c0caf5ff",
            "border": "#414868ff",
            "accent": "#7aa2f7ff",
        },
    },
    "storage": {
        "conversations_dir": "",
        "archive_dir": "",
    },
    "tools": {
        "dirs": [],
    },
    "notifications": {},
    "status": {
        "signal": 12,
    },
}

# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*.

    - Nested dicts are merged recursively.
    - All other types are replaced by the override value.
    - *base* is never mutated.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load configuration from a TOML file and merge over defaults.

    If *path* is ``None``, resolve via ``$XDG_CONFIG_HOME/aside/config.toml``
    (falling back to ``~/.config/aside/config.toml``).  When the file does not
    exist, the unmodified defaults are returned.
    """
    if path is None:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            config_dir = Path(xdg) / "aside"
        else:
            config_dir = Path.home() / ".config" / "aside"
        path = config_dir / "config.toml"
    else:
        path = Path(path)

    if not path.is_file():
        return copy.deepcopy(DEFAULT_CONFIG)

    with open(path, "rb") as fh:
        user = tomllib.load(fh)

    return _deep_merge(DEFAULT_CONFIG, user)


# ---------------------------------------------------------------------------
# XDG path resolution helpers
# ---------------------------------------------------------------------------


def resolve_state_dir(cfg: dict[str, Any]) -> Path:
    """Return the aside state directory (``$XDG_STATE_HOME/aside``)."""
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "aside"
    return Path.home() / ".local" / "state" / "aside"


def resolve_conversations_dir(cfg: dict[str, Any]) -> Path:
    """Return the conversations directory (JSON state files).

    Uses ``cfg["storage"]["conversations_dir"]`` when set, otherwise
    ``<state_dir>/conversations``.
    """
    custom = cfg.get("storage", {}).get("conversations_dir", "")
    if custom:
        return Path(custom).expanduser()
    return resolve_state_dir(cfg) / "conversations"


def resolve_archive_dir(cfg: dict[str, Any]) -> Path:
    """Return the archive directory (exported markdown transcripts).

    Uses ``cfg["storage"]["archive_dir"]`` when set, otherwise
    ``<state_dir>/archive``.
    """
    custom = cfg.get("storage", {}).get("archive_dir", "")
    if custom:
        return Path(custom).expanduser()
    return resolve_state_dir(cfg) / "archive"


def resolve_socket_path(name: str = "aside.sock") -> Path:
    """Return the Unix socket path inside ``$XDG_RUNTIME_DIR``."""
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / name
    return Path(f"/run/user/{os.getuid()}") / name


def resolve_excluded_models_path() -> Path:
    """Return the path to the excluded-models file."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "aside" / "excluded-models"
    return Path.home() / ".config" / "aside" / "excluded-models"


def load_excluded_models() -> list[str]:
    """Load the excluded models list from the excluded-models file.

    One model per line.  Blank lines and ``#`` comments are ignored.
    Returns an empty list if the file doesn't exist.
    """
    path = resolve_excluded_models_path()
    if not path.is_file():
        return []
    models = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            models.append(line)
    return models
