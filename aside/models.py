"""Model discovery — available models filtered by API key availability."""

from __future__ import annotations

import os
import re

from aside.keyring import _PROVIDER_TO_ENV, get_key as keyring_get_key

# Keyring provider name -> litellm.models_by_provider key.
_LITELLM_PROVIDERS: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "gemini",
    "groq": "groq",
    "mistral": "mistral",
    "cohere": "cohere_chat",
    "together": "together_ai",
    "deepseek": "deepseek",
}

# Models matching any of these patterns are not chat-completable.
_NON_CHAT_RE = re.compile(
    r"embed|image|tts|audio|whisper|dall-e|imagen|moderation|realtime",
    re.IGNORECASE,
)


def _get_registry() -> dict[str, set[str]]:
    """Return litellm.models_by_provider (import deferred)."""
    import litellm
    return litellm.models_by_provider


def available_providers() -> list[str]:
    """Return provider names that have an API key available."""
    result = []
    for provider, env_var in _PROVIDER_TO_ENV.items():
        if os.environ.get(env_var):
            result.append(provider)
        elif keyring_get_key(provider):
            result.append(provider)
    return result


def available_models() -> dict[str, list[str]]:
    """Return chat models grouped by provider, filtered to keyed providers.

    Each model name is normalized to ``provider/model`` format.
    """
    providers = available_providers()
    if not providers:
        return {}

    registry = _get_registry()
    result: dict[str, list[str]] = {}

    for provider in providers:
        litellm_key = _LITELLM_PROVIDERS.get(provider)
        if litellm_key is None:
            continue

        raw_models = registry.get(litellm_key, set())
        seen: set[str] = set()

        for name in raw_models:
            if _NON_CHAT_RE.search(name):
                continue

            # Normalize to provider/model
            if "/" not in name:
                name = f"{litellm_key}/{name}"

            if name not in seen:
                seen.add(name)

        if seen:
            result[provider] = sorted(seen)

    return result
