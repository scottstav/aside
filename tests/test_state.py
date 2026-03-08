"""Tests for aside.state — conversation store, usage log, and status state."""

import json
import time
from pathlib import Path
from unittest import mock

import pytest


def _import_state():
    """Import state module from the package directory."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "aside.state", Path(__file__).parent.parent / "aside" / "state.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# ConversationStore
# ---------------------------------------------------------------------------


class TestConversationStore:
    """Verify conversation JSON file management."""

    @pytest.fixture(autouse=True)
    def _load(self, tmp_path):
        self.mod = _import_state()
        self.conv_dir = tmp_path / "conversations"
        self.store = self.mod.ConversationStore(self.conv_dir)

    def test_init_creates_directory(self):
        assert self.conv_dir.is_dir()

    def test_get_or_create_new(self):
        conv = self.store.get_or_create()
        assert "id" in conv
        assert "created" in conv
        assert conv["messages"] == []
        # id should be a valid UUID string
        assert len(conv["id"]) == 36

    def test_get_or_create_with_id(self):
        conv = self.store.get_or_create(conv_id="custom-123")
        assert conv["id"] == "custom-123"
        assert conv["messages"] == []

    def test_save_and_load(self):
        conv = self.store.get_or_create()
        conv["messages"].append({"role": "user", "content": "hello"})
        self.store.save(conv)

        # File should exist
        path = self.conv_dir / f"{conv['id']}.json"
        assert path.exists()

        # Load it back
        loaded = self.store.get_or_create(conv_id=conv["id"])
        assert loaded["id"] == conv["id"]
        assert loaded["messages"] == [{"role": "user", "content": "hello"}]

    def test_save_pretty_prints(self):
        conv = self.store.get_or_create()
        self.store.save(conv)
        path = self.conv_dir / f"{conv['id']}.json"
        text = path.read_text()
        # Pretty-printed JSON has newlines and indentation
        assert "\n" in text
        assert "  " in text

    def test_get_or_create_nonexistent_id(self):
        """If conv_id is given but file doesn't exist, create new with that id."""
        conv = self.store.get_or_create(conv_id="does-not-exist")
        assert conv["id"] == "does-not-exist"
        assert conv["messages"] == []

    def test_save_last(self, tmp_path):
        self.store.save_last("abc-123")
        last_file = self.conv_dir.parent / "last.json"
        assert last_file.exists()
        data = json.loads(last_file.read_text())
        assert data["conversation_id"] == "abc-123"
        assert "timestamp" in data

    def test_resolve_last(self, tmp_path):
        """resolve_last returns conv_id from last.json."""
        self.store.save_last("recent-conv")
        result = self.store.resolve_last()
        assert result == "recent-conv"

    def test_resolve_last_no_file(self):
        """resolve_last returns None when last.json doesn't exist."""
        result = self.store.resolve_last()
        assert result is None

    def test_list_recent_empty(self):
        result = self.store.list_recent()
        assert result == []

    def test_list_recent_returns_conversations(self):
        # Create a few conversations
        for i in range(3):
            conv = self.store.get_or_create()
            conv["messages"].append({"role": "user", "content": f"message {i}"})
            self.store.save(conv)
            time.sleep(0.01)  # ensure distinct mtime

        result = self.store.list_recent(limit=20)
        assert len(result) == 3
        # Each entry is (id, created, preview)
        for conv_id, created, preview in result:
            assert isinstance(conv_id, str)
            assert isinstance(created, str)
            assert isinstance(preview, str)

    def test_list_recent_respects_limit(self):
        for i in range(5):
            conv = self.store.get_or_create()
            conv["messages"].append({"role": "user", "content": f"msg {i}"})
            self.store.save(conv)
            time.sleep(0.01)

        result = self.store.list_recent(limit=2)
        assert len(result) == 2

    def test_list_recent_most_recent_first(self):
        """Most recently modified conversations come first."""
        ids = []
        for i in range(3):
            conv = self.store.get_or_create()
            conv["messages"].append({"role": "user", "content": f"msg {i}"})
            self.store.save(conv)
            ids.append(conv["id"])
            time.sleep(0.01)

        result = self.store.list_recent()
        result_ids = [r[0] for r in result]
        # Most recent first
        assert result_ids[0] == ids[-1]

    def test_list_recent_preview_from_first_user_message(self):
        conv = self.store.get_or_create()
        conv["messages"].append({"role": "assistant", "content": "Hi!"})
        conv["messages"].append({"role": "user", "content": "What is the weather?"})
        self.store.save(conv)

        result = self.store.list_recent()
        assert len(result) == 1
        _, _, preview = result[0]
        assert "weather" in preview.lower()

    def test_list_recent_no_user_message(self):
        """Conversations with no user messages get empty preview."""
        conv = self.store.get_or_create()
        conv["messages"].append({"role": "assistant", "content": "Hi!"})
        self.store.save(conv)

        result = self.store.list_recent()
        assert len(result) == 1
        _, _, preview = result[0]
        assert preview == ""


# ---------------------------------------------------------------------------
# UsageLog
# ---------------------------------------------------------------------------


class TestUsageLog:
    """Verify append-only JSONL usage logging."""

    @pytest.fixture(autouse=True)
    def _load(self, tmp_path):
        self.mod = _import_state()
        self.log_path = tmp_path / "usage.jsonl"
        self.usage = self.mod.UsageLog(self.log_path)

    def test_log_creates_file(self):
        self.usage.log("claude-sonnet-4-6", 100, 200)
        assert self.log_path.exists()

    def test_log_appends_jsonl(self):
        self.usage.log("claude-sonnet-4-6", 100, 200)
        self.usage.log("claude-sonnet-4-6", 300, 400)

        lines = self.log_path.read_text().strip().splitlines()
        assert len(lines) == 2

        entry = json.loads(lines[0])
        assert entry["model"] == "claude-sonnet-4-6"
        assert entry["input_tokens"] == 100
        assert entry["output_tokens"] == 200
        assert "cost_usd" not in entry
        assert "ts" in entry

    def test_log_entry_has_timestamp(self):
        self.usage.log("model", 10, 20)
        entry = json.loads(self.log_path.read_text().strip())
        # Timestamp should be ISO-ish format with YYYY-MM prefix
        assert entry["ts"][:4].isdigit()

    def test_log_creates_parent_dirs(self, tmp_path):
        deep_path = tmp_path / "a" / "b" / "c" / "usage.jsonl"
        usage = self.mod.UsageLog(deep_path)
        usage.log("model", 10, 20)
        assert deep_path.exists()


# ---------------------------------------------------------------------------
# StatusState
# ---------------------------------------------------------------------------


class TestStatusState:
    """Verify status JSON management for status bar integration."""

    @pytest.fixture(autouse=True)
    def _load(self, tmp_path):
        self.mod = _import_state()
        self.state_dir = tmp_path / "state"
        # Create a usage log for month_cost reads
        self.usage_path = self.state_dir / "usage.jsonl"
        # Patch subprocess to avoid actually signaling waybar
        with mock.patch("subprocess.Popen"):
            self.status = self.mod.StatusState(
                state_dir=self.state_dir,
                signal_num=12,
                usage_log_path=self.usage_path,
            )

    def test_init_creates_state_dir(self):
        assert self.state_dir.is_dir()

    def test_init_writes_status_json(self):
        status_file = self.state_dir / "status.json"
        assert status_file.exists()
        data = json.loads(status_file.read_text())
        assert data["status"] == "idle"

    def test_set_status(self):
        with mock.patch("subprocess.Popen"):
            self.status.set_status("thinking")
        data = json.loads((self.state_dir / "status.json").read_text())
        assert data["status"] == "thinking"
        assert data["tool_name"] == ""

    def test_set_status_with_tool(self):
        with mock.patch("subprocess.Popen"):
            self.status.set_status("tool_use", tool_name="web_search")
        data = json.loads((self.state_dir / "status.json").read_text())
        assert data["status"] == "tool_use"
        assert data["tool_name"] == "web_search"

    def test_speak_enabled_default_false(self):
        assert self.status.speak_enabled is False

    def test_speak_enabled_toggle(self):
        with mock.patch("subprocess.Popen"):
            self.status.speak_enabled = True
        assert self.status.speak_enabled is True
        data = json.loads((self.state_dir / "status.json").read_text())
        assert data["speak_enabled"] is True

        with mock.patch("subprocess.Popen"):
            self.status.speak_enabled = False
        assert self.status.speak_enabled is False

    def test_update_usage(self):
        with mock.patch("subprocess.Popen"):
            self.status.update_usage(total_tokens=5000)
        data = json.loads((self.state_dir / "status.json").read_text())
        assert data["usage"]["total_tokens"] == 5000
        assert "month_cost" not in data["usage"]
        assert "last_query_cost" not in data["usage"]

    def test_set_model(self):
        with mock.patch("subprocess.Popen"):
            self.status.set_model("gemini/gemini-2.5-pro")
        data = json.loads((self.state_dir / "status.json").read_text())
        assert data["model"] == "gemini/gemini-2.5-pro"

    def test_signal_bar_uses_configured_signal(self):
        with mock.patch("subprocess.Popen") as mock_popen:
            self.status.set_status("thinking")
            mock_popen.assert_called()
            args = mock_popen.call_args[0][0]
            assert "pkill" in args
            assert "-SIGRTMIN+12" in args[1]

    def test_signal_bar_custom_signal(self, tmp_path):
        state_dir = tmp_path / "custom_state"
        usage_path = state_dir / "usage.jsonl"
        with mock.patch("subprocess.Popen") as mock_popen:
            status = self.mod.StatusState(
                state_dir=state_dir,
                signal_num=8,
                usage_log_path=usage_path,
            )
            mock_popen.reset_mock()
            status.set_status("idle")
            args = mock_popen.call_args[0][0]
            assert "-SIGRTMIN+8" in args[1]
