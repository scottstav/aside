"""State management — conversation store, usage log, and status bar state."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Conversation store
# ---------------------------------------------------------------------------


class ConversationStore:
    """Load and save conversation JSON files.

    All paths are explicit — no hardcoded defaults.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path_for(self, conv_id: str) -> Path:
        return self.directory / f"{conv_id}.json"

    def get_or_create(self, conv_id: str | None = None) -> dict:
        """Load an existing conversation or create a new one.

        If *conv_id* is given and the file exists, load from JSON.
        Otherwise create a new conversation dict with the given (or generated) id.
        """
        if conv_id:
            path = self._path_for(conv_id)
            if path.exists():
                with open(path) as f:
                    return json.load(f)
        new_id = conv_id or str(uuid.uuid4())
        return {
            "id": new_id,
            "created": datetime.now(timezone.utc).isoformat(),
            "messages": [],
        }

    def save(self, conv: dict) -> None:
        """Write conversation dict to ``{conv_id}.json``, pretty-printed."""
        path = self._path_for(conv["id"])
        with open(path, "w") as f:
            json.dump(conv, f, indent=2)
        log.info(
            "Saved conversation %s (%d messages)",
            conv["id"][:8],
            len(conv["messages"]),
        )

    def save_last(self, conv_id: str) -> None:
        """Write ``last.json`` to the parent directory of the conversations dir.

        Contains the conversation id and a Unix timestamp so callers can
        auto-resolve to the most recent conversation within a time window.
        """
        last_file = self.directory.parent / "last.json"
        try:
            last_file.parent.mkdir(parents=True, exist_ok=True)
            last_file.write_text(json.dumps({
                "conversation_id": conv_id,
                "timestamp": time.time(),
            }))
        except OSError:
            log.exception("Failed to write last.json")

    def auto_resolve(self, max_age_seconds: int = 60) -> str | None:
        """Return the last conversation id if it was saved recently.

        Reads ``last.json`` from the parent directory.  If the file exists and
        its timestamp is within *max_age_seconds* of now, return the
        conversation id.  Otherwise return ``None``.
        """
        last_file = self.directory.parent / "last.json"
        try:
            data = json.loads(last_file.read_text())
            conv_id = data.get("conversation_id")
            ts = data.get("timestamp", 0)
            if conv_id and (time.time() - ts) < max_age_seconds:
                return conv_id
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return None

    @staticmethod
    def transcript_path(conv_id: str) -> Path:
        """Return the path to the live markdown transcript for a conversation."""
        return Path(f"/tmp/aside-{conv_id[:8]}.md")

    @staticmethod
    def _extract_user_text(content) -> str:
        """Extract text from user message content (plain string or multimodal)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
            return " ".join(parts)
        return ""

    def write_transcript(self, conv: dict) -> None:
        """Write a markdown transcript of the conversation to /tmp.

        Called incrementally during query streaming so an editor with
        auto-reload-from-disk shows the conversation as it happens.
        """
        conv_id = conv.get("id", "unknown")
        lines = [f"# Conversation {conv_id[:8]}", ""]

        for msg in conv.get("messages", []):
            role = msg.get("role", "")

            if role == "user":
                lines.append("## User")
                lines.append("")
                text = self._extract_user_text(msg.get("content", ""))
                lines.append(text)
                lines.append("")

            elif role == "assistant":
                content = msg.get("content")
                if content:
                    lines.append("## Assistant")
                    lines.append("")
                    lines.append(content)
                    lines.append("")

        md_path = self.transcript_path(conv_id)
        try:
            md_path.write_text("\n".join(lines))
        except OSError:
            log.exception("Failed to write transcript to %s", md_path)

    def list_recent(self, limit: int = 20) -> list[tuple[str, str, str]]:
        """List recent conversations ordered by modification time (newest first).

        Returns a list of ``(id, created, first_user_message_preview)`` tuples.
        """
        files = sorted(
            self.directory.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]

        results: list[tuple[str, str, str]] = []
        for path in files:
            try:
                with open(path) as f:
                    conv = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            conv_id = conv.get("id", path.stem)
            created = conv.get("created", "")

            # Find first user message for preview
            preview = ""
            for msg in conv.get("messages", []):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        preview = content[:120]
                    elif isinstance(content, list):
                        parts = []
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                parts.append(part.get("text", ""))
                        preview = " ".join(parts)[:120]
                    break

            results.append((conv_id, created, preview))

        return results


# ---------------------------------------------------------------------------
# Usage log
# ---------------------------------------------------------------------------


class UsageLog:
    """Append-only JSONL log of API usage.

    All paths are explicit — no hardcoded defaults.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def log(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Append one JSON line with a timestamp."""
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            log.exception("Failed to write usage log")


# ---------------------------------------------------------------------------
# Status state
# ---------------------------------------------------------------------------


class StatusState:
    """Manage the status JSON file for status bar integration.

    All paths are explicit — no hardcoded defaults.  The signal number
    is configurable (not hardcoded to 12).
    """

    def __init__(
        self,
        state_dir: Path,
        signal_num: int = 12,
        usage_log_path: Path | None = None,
        model: str = DEFAULT_MODEL,
        speak_enabled: bool = False,
    ) -> None:
        self._state_dir = Path(state_dir)
        self._signal_num = signal_num
        self._lock = threading.Lock()

        self._state: dict = {
            "status": "idle",
            "tool_name": "",
            "model": model,
            "speak_enabled": speak_enabled,
            "usage": {
                "total_tokens": 0,
            },
        }

        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._write()

    @property
    def speak_enabled(self) -> bool:
        return self._state["speak_enabled"]

    @speak_enabled.setter
    def speak_enabled(self, val: bool) -> None:
        with self._lock:
            self._state["speak_enabled"] = val
            self._write()

    @property
    def status(self) -> str:
        return self._state["status"]

    def set_status(self, status: str, tool_name: str = "") -> None:
        """Set status to idle, thinking, speaking, or tool_use.  Writes + signals."""
        with self._lock:
            self._state["status"] = status
            self._state["tool_name"] = tool_name
            self._write()

    def update_usage(self, total_tokens: int) -> None:
        """Update token count after an API call."""
        with self._lock:
            self._state["usage"]["total_tokens"] = total_tokens
            self._write()

    def reload_model(self, config_path: Path) -> None:
        """Re-read model name from config.toml and update state."""
        with self._lock:
            self._state["model"] = _read_model_from_config(config_path)
            self._write()

    def reload_speak_enabled(self) -> None:
        """Re-read the state file to pick up toggle changes from external scripts."""
        with self._lock:
            try:
                status_file = self._state_dir / "status.json"
                if status_file.exists():
                    data = json.loads(status_file.read_text())
                    self._state["speak_enabled"] = data.get("speak_enabled", False)
            except (json.JSONDecodeError, OSError):
                pass

    def _write(self) -> None:
        """Write state to disk and signal the status bar."""
        try:
            status_file = self._state_dir / "status.json"
            status_file.write_text(json.dumps(self._state, indent=2))
        except OSError:
            log.exception("Failed to write status state")
        self._signal_bar()

    def _signal_bar(self) -> None:
        """Send SIGRTMIN+N to waybar for immediate refresh."""
        try:
            subprocess.Popen(
                ["pkill", f"-SIGRTMIN+{self._signal_num}", "waybar"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_model_from_config(config_path: Path) -> str:
    """Read the model name from a TOML config file."""
    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        return config.get("model", {}).get("name", DEFAULT_MODEL)
    except (FileNotFoundError, tomllib.TOMLDecodeError, OSError):
        return DEFAULT_MODEL
