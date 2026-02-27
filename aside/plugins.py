"""Plugin system — load and execute tool plugins from directories.

Each tool is a .py file with a ``TOOL_SPEC`` dict and a ``run()`` function.

``TOOL_SPEC`` follows the OpenAI function-calling schema::

    TOOL_SPEC = {
        "name": "my_tool",
        "description": "Does something useful",
        "parameters": {
            "type": "object",
            "properties": { ... },
            "required": [ ... ],
        },
    }

``run()`` takes keyword arguments matching the parameters and returns a string
(or a dict for special types like images).
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Module cache: keyed by tool name → loaded module.  Populated by
# load_tools(), consumed by run_tool().  Cleared by clear_cache().
_module_cache: dict[str, object] = {}


def clear_cache() -> None:
    """Clear the loaded-module cache (useful for tests or plugin reload)."""
    _module_cache.clear()


def _load_module(path: Path) -> object | None:
    """Import a single .py file and return the module, or None on failure."""
    try:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        log.warning("Failed to load plugin from %s", path, exc_info=True)
        return None


def load_tools(dirs: list[Path]) -> list[dict]:
    """Scan *dirs* for .py tool plugins and return OpenAI-format tool dicts.

    Each valid plugin contributes one entry::

        {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}

    Broken or incomplete modules are skipped with a warning.
    Also populates the module cache so that ``run_tool`` can execute tools
    without re-scanning the filesystem.
    """
    tools: list[dict] = []
    seen_names: set[str] = set()

    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            mod = _load_module(path)
            if mod is None:
                continue

            tool_spec = getattr(mod, "TOOL_SPEC", None)
            if tool_spec is None:
                log.warning("No TOOL_SPEC in %s — skipping", path)
                continue

            name = tool_spec.get("name")
            if not name:
                log.warning("TOOL_SPEC in %s has no name — skipping", path)
                continue

            if name in seen_names:
                log.debug("Duplicate tool name %r from %s — skipping", name, path)
                continue
            seen_names.add(name)

            _module_cache[name] = mod
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool_spec.get("description", ""),
                    "parameters": tool_spec.get("parameters", {}),
                },
            })
            log.info("Loaded tool: %s (%s)", name, path.name)

    return tools


def run_tool(name: str, input_data: dict, dirs: list[Path]) -> str | dict:
    """Find a tool by *name* and execute it.

    Uses the module cache populated by ``load_tools``.  Falls back to a
    directory scan if the tool is not cached (e.g. hot-loaded plugin).

    Returns the tool's result (a string, or a dict for special types like
    images).  If the tool is not found or raises an exception, an error string
    is returned instead.
    """
    # Fast path: use cached module
    mod = _module_cache.get(name)

    # Slow path: scan dirs (plugin added after load_tools was called)
    if mod is None:
        for directory in dirs:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.py")):
                m = _load_module(path)
                if m is None:
                    continue
                ts = getattr(m, "TOOL_SPEC", None)
                if ts and ts.get("name") == name:
                    _module_cache[name] = m
                    mod = m
                    break
            if mod is not None:
                break

    if mod is None:
        return f"Error: tool {name} not found"

    try:
        result = mod.run(**input_data)
        if isinstance(result, dict) and result.get("type") == "image":
            return result
        return str(result)
    except Exception:
        log.exception("Error running tool %s", name)
        return f"Error: tool {name} raised an exception"
