"""Tests for the plugin loading system."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from aside.plugins import clear_cache, load_tools, run_tool


@pytest.fixture(autouse=True)
def _clean_plugin_cache():
    """Clear the module cache before each test."""
    clear_cache()
    yield
    clear_cache()


@pytest.fixture()
def tool_dir(tmp_path: Path) -> Path:
    """Create a temp directory with a valid tool plugin."""
    tool_file = tmp_path / "greet.py"
    tool_file.write_text(textwrap.dedent("""\
        TOOL_SPEC = {
            "name": "greet",
            "description": "Say hello",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Who to greet"},
                },
                "required": ["name"],
            },
        }

        def run(name: str) -> str:
            return f"Hello, {name}!"
    """))
    return tmp_path


@pytest.fixture()
def multi_tool_dir(tmp_path: Path) -> Path:
    """Create a temp directory with two valid tool plugins."""
    (tmp_path / "greet.py").write_text(textwrap.dedent("""\
        TOOL_SPEC = {
            "name": "greet",
            "description": "Say hello",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Who to greet"},
                },
                "required": ["name"],
            },
        }

        def run(name: str) -> str:
            return f"Hello, {name}!"
    """))
    (tmp_path / "add.py").write_text(textwrap.dedent("""\
        TOOL_SPEC = {
            "name": "add",
            "description": "Add two numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "description": "First number"},
                    "b": {"type": "integer", "description": "Second number"},
                },
                "required": ["a", "b"],
            },
        }

        def run(a: int, b: int) -> str:
            return str(a + b)
    """))
    return tmp_path


@pytest.fixture()
def broken_dir(tmp_path: Path) -> Path:
    """Create a temp directory with a broken and a valid plugin."""
    (tmp_path / "broken.py").write_text("raise RuntimeError('oops')\n")
    (tmp_path / "good.py").write_text(textwrap.dedent("""\
        TOOL_SPEC = {
            "name": "good",
            "description": "A working tool",
            "parameters": {"type": "object", "properties": {}},
        }

        def run() -> str:
            return "works"
    """))
    return tmp_path


# ── load_tools ──────────────────────────────────────────────────────


class TestLoadTools:
    def test_loads_valid_tool(self, tool_dir: Path):
        tools = load_tools([tool_dir])
        assert len(tools) == 1
        tool = tools[0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "greet"
        assert tool["function"]["description"] == "Say hello"
        assert "properties" in tool["function"]["parameters"]

    def test_returns_openai_format(self, tool_dir: Path):
        """Each entry must be {"type": "function", "function": {...}}."""
        tools = load_tools([tool_dir])
        for tool in tools:
            assert set(tool.keys()) == {"type", "function"}
            assert tool["type"] == "function"
            fn = tool["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn

    def test_loads_multiple_tools(self, multi_tool_dir: Path):
        tools = load_tools([multi_tool_dir])
        names = {t["function"]["name"] for t in tools}
        assert names == {"greet", "add"}

    def test_skips_broken_plugins(self, broken_dir: Path):
        tools = load_tools([broken_dir])
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "good"

    def test_empty_directory(self, tmp_path: Path):
        tools = load_tools([tmp_path])
        assert tools == []

    def test_nonexistent_directory(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist"
        tools = load_tools([missing])
        assert tools == []

    def test_multiple_directories(self, tool_dir: Path, multi_tool_dir: Path):
        tools = load_tools([tool_dir, multi_tool_dir])
        names = {t["function"]["name"] for t in tools}
        # tool_dir has greet, multi_tool_dir has greet + add
        assert "greet" in names
        assert "add" in names

    def test_skips_file_without_tool_spec(self, tmp_path: Path):
        """A .py file without TOOL_SPEC should be skipped silently."""
        (tmp_path / "no_spec.py").write_text("x = 1\n")
        tools = load_tools([tmp_path])
        assert tools == []


# ── run_tool ────────────────────────────────────────────────────────


class TestRunTool:
    def test_runs_correct_tool(self, tool_dir: Path):
        result = run_tool("greet", {"name": "World"}, [tool_dir])
        assert result == "Hello, World!"

    def test_returns_error_for_unknown_tool(self, tool_dir: Path):
        result = run_tool("nonexistent", {}, [tool_dir])
        assert isinstance(result, str)
        assert "not found" in result.lower()

    def test_runs_tool_with_multiple_args(self, multi_tool_dir: Path):
        result = run_tool("add", {"a": 3, "b": 4}, [multi_tool_dir])
        assert result == "7"

    def test_returns_error_on_tool_exception(self, tmp_path: Path):
        (tmp_path / "failing.py").write_text(textwrap.dedent("""\
            TOOL_SPEC = {
                "name": "failing",
                "description": "Always fails",
                "parameters": {"type": "object", "properties": {}},
            }

            def run() -> str:
                raise ValueError("kaboom")
        """))
        result = run_tool("failing", {}, [tmp_path])
        assert isinstance(result, str)
        assert "error" in result.lower()

    def test_returns_dict_for_image_type(self, tmp_path: Path):
        """Tools that return image dicts should pass through."""
        (tmp_path / "img_tool.py").write_text(textwrap.dedent("""\
            TOOL_SPEC = {
                "name": "img_tool",
                "description": "Returns an image",
                "parameters": {"type": "object", "properties": {}},
            }

            def run() -> dict:
                return {"type": "image", "data": "abc", "media_type": "image/png"}
        """))
        result = run_tool("img_tool", {}, [tmp_path])
        assert isinstance(result, dict)
        assert result["type"] == "image"

    def test_searches_multiple_dirs(self, tool_dir: Path, multi_tool_dir: Path):
        result = run_tool("add", {"a": 10, "b": 20}, [tool_dir, multi_tool_dir])
        assert result == "30"
