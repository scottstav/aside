"""Persistent memory -- save and recall information across conversations."""

import os
from datetime import datetime
from pathlib import Path

TOOL_SPEC = {
    "name": "memory",
    "description": (
        "Save and recall information across conversations. Use this proactively "
        "whenever the user mentions plans, intentions, ideas, preferences, "
        "decisions, or anything they might want to remember later -- even if "
        "they don't explicitly ask you to remember it.\n\n"
        "Actions:\n"
        "- save: Store a memory. Write a clear, self-contained summary (not "
        "the user's raw words). Include enough context that it makes sense on "
        "its own later.\n"
        "- search: Find memories by keyword. Returns matching entries with context.\n"
        "- recent: Show the most recent memories (default 10).\n"
        "- delete: Remove a memory by its exact timestamp prefix (YYYY-MM-DD HH:MM)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save", "search", "recent", "delete"],
                "description": (
                    "What to do: save a new memory, search existing ones, "
                    "show recent, or delete one."
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "For 'save': the memory to store. Write a clear summary, "
                    "not raw user words."
                ),
            },
            "query": {
                "type": "string",
                "description": "For 'search': keywords to find in memories.",
            },
            "count": {
                "type": "integer",
                "description": "For 'recent': how many entries to show (default 10).",
            },
            "timestamp": {
                "type": "string",
                "description": (
                    "For 'delete': the timestamp prefix of the entry to "
                    "remove (e.g. '2026-02-26 14:30')."
                ),
            },
        },
        "required": ["action"],
    },
}


def _memory_file() -> Path:
    """Return the memory file path using XDG conventions."""
    xdg = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(xdg) / "aside" / "memory.md"


def _ensure_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Aside Memory\n\n")


def _save(path: Path, content: str) -> str:
    _ensure_file(path)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"- **{ts}** -- {content}\n"
    with open(path, "a") as f:
        f.write(entry)
    return "Saved to memory."


def _search(path: Path, query: str) -> str:
    _ensure_file(path)
    text = path.read_text()
    lines = text.splitlines()
    terms = query.lower().split()
    matches = []
    for line in lines:
        if line.startswith("- **"):
            lower = line.lower()
            score = sum(1 for t in terms if t in lower)
            if score > 0:
                matches.append((score, line))
    if not matches:
        return f"No memories found matching: {query}"
    matches.sort(key=lambda x: x[0], reverse=True)
    results = [line for _, line in matches[:20]]
    return f"Found {len(matches)} matching memories:\n\n" + "\n".join(results)


def _recent(path: Path, count: int = 10) -> str:
    _ensure_file(path)
    text = path.read_text()
    entries = [line for line in text.splitlines() if line.startswith("- **")]
    if not entries:
        return "No memories saved yet."
    recent = entries[-count:]
    return f"Last {len(recent)} memories:\n\n" + "\n".join(recent)


def _delete(path: Path, timestamp: str) -> str:
    _ensure_file(path)
    text = path.read_text()
    lines = text.splitlines()
    new_lines = []
    removed = 0
    for line in lines:
        if line.startswith("- **") and timestamp in line:
            removed += 1
            continue
        new_lines.append(line)
    if removed == 0:
        return f"No memory found with timestamp '{timestamp}'."
    path.write_text("\n".join(new_lines) + "\n")
    return f"Removed {removed} memory entry."


def run(
    action: str,
    content: str | None = None,
    query: str | None = None,
    count: int = 10,
    timestamp: str | None = None,
) -> str:
    """Execute a memory action."""
    path = _memory_file()

    if action == "save":
        if not content or not content.strip():
            return "Error: 'content' is required for save."
        return _save(path, content.strip())

    elif action == "search":
        if not query or not query.strip():
            return "Error: 'query' is required for search."
        return _search(path, query.strip())

    elif action == "recent":
        return _recent(path, count)

    elif action == "delete":
        if not timestamp or not timestamp.strip():
            return "Error: 'timestamp' is required for delete."
        return _delete(path, timestamp.strip())

    return f"Unknown action: {action}"
