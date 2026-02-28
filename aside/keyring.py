"""Desktop keyring integration — KWallet and GNOME Keyring via subprocess."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("aside")


# Provider name <-> env var mapping.
_PROVIDER_TO_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "together": "TOGETHER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

_ENV_TO_PROVIDER = {v: k for k, v in _PROVIDER_TO_ENV.items()}


def _kwallet_available() -> bool:
    """Check if kwalletcli tools are installed."""
    return shutil.which("kwalletcli-getentry") is not None


def _gnome_available() -> bool:
    """Check if GNOME secret-tool is installed."""
    return shutil.which("secret-tool") is not None


def _env_file_path() -> Path:
    """Return path to the EnvironmentFile (~/.config/aside/env)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "aside" / "env"
    return Path.home() / ".config" / "aside" / "env"


def get_key(provider: str) -> str | None:
    """Retrieve an API key from the first available desktop keyring.

    Tries KWallet first, then GNOME Keyring.  Returns None if neither
    backend is available or the key isn't stored.
    """
    if _kwallet_available():
        try:
            result = subprocess.run(
                ["kwalletcli-getentry", "-f", "aside", "-e", f"{provider}-api-key"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                log.info("Retrieved %s key from KWallet", provider)
                return result.stdout.strip()
        except subprocess.TimeoutExpired:
            log.warning("KWallet lookup timed out for %s", provider)

    if _gnome_available():
        try:
            result = subprocess.run(
                ["secret-tool", "lookup", "service", "aside", "provider", provider],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                log.info("Retrieved %s key from GNOME Keyring", provider)
                return result.stdout.strip()
        except subprocess.TimeoutExpired:
            log.warning("secret-tool lookup timed out for %s", provider)

    return None


def set_key(provider: str, key: str) -> str:
    """Store an API key in the first available backend.

    Returns the backend name: 'kwallet', 'gnome-keyring', or 'env-file'.
    """
    if _kwallet_available():
        try:
            result = subprocess.run(
                ["kwalletcli-setentry", "-f", "aside", "-e", f"{provider}-api-key"],
                input=key,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                log.info("Stored %s key in KWallet", provider)
                return "kwallet"
        except subprocess.TimeoutExpired:
            log.warning("KWallet store timed out for %s", provider)

    if _gnome_available():
        try:
            result = subprocess.run(
                [
                    "secret-tool", "store",
                    f"--label=aside: {provider} API key",
                    "service", "aside",
                    "provider", provider,
                ],
                input=key,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                log.info("Stored %s key in GNOME Keyring", provider)
                return "gnome-keyring"
        except subprocess.TimeoutExpired:
            log.warning("secret-tool store timed out for %s", provider)

    # Fall back to env file
    env_var = _PROVIDER_TO_ENV.get(provider, f"{provider.upper()}_API_KEY")
    env_file = _env_file_path()
    env_file.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if not line.startswith(f"{env_var}="):
                lines.append(line)
    lines.append(f"{env_var}={key}")

    env_file.write_text("\n".join(lines) + "\n")
    env_file.chmod(0o600)
    log.info("Stored %s key in %s", provider, env_file)
    return "env-file"


def load_keyring_keys() -> None:
    """Load API keys from desktop keyrings into env vars.

    Only sets vars that aren't already in the environment.
    Called during daemon startup, after _restore_api_keys() and before
    _cache_api_keys().
    """
    for env_var, provider in _ENV_TO_PROVIDER.items():
        if env_var in os.environ:
            continue
        key = get_key(provider)
        if key:
            os.environ[env_var] = key
