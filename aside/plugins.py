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


def load_tools(dirs: list[Path]) -> list[dict]:
    """Scan *dirs* for .py tool plugins and return OpenAI-format tool dicts.

    Each valid plugin contributes one entry::

        {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}

    Broken or incomplete modules are skipped with a warning.
    """
    tools: list[dict] = []
    seen_names: set[str] = set()

    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            try:
                spec = importlib.util.spec_from_file_location(path.stem, path)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                log.warning("Failed to load plugin from %s", path, exc_info=True)
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
    """Find a tool by *name* across *dirs* and execute it.

    Returns the tool's result (a string, or a dict for special types like
    images).  If the tool is not found or raises an exception, an error string
    is returned instead.
    """
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            try:
                spec = importlib.util.spec_from_file_location(path.stem, path)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                log.warning("Failed to import tool %s", path.name, exc_info=True)
                continue

            tool_spec = getattr(mod, "TOOL_SPEC", None)
            if tool_spec is None or tool_spec.get("name") != name:
                continue

            try:
                result = mod.run(**input_data)
                if isinstance(result, dict) and result.get("type") == "image":
                    return result
                return str(result)
            except Exception:
                log.exception("Error running tool %s", name)
                return f"Error: tool {name} raised an exception"

    return f"Error: tool {name} not found"
