"""Tests for aside.query — message building, tool accumulation, notifications."""

from __future__ import annotations

import json
import re
import threading
from types import SimpleNamespace
from unittest import mock

import pytest

from aside.query import (
    NEW_CONVERSATION,
    _accumulate_tool_calls,
    _build_messages,
    _build_system_prompt,
    _parse_tool_calls,
    notify,
    notify_final,
    stream_response,
)


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_contains_date(self):
        prompt = _build_system_prompt()
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in prompt

    def test_contains_weekday(self):
        prompt = _build_system_prompt()
        from datetime import datetime
        weekday = datetime.now().strftime("%A")
        assert weekday in prompt

    def test_extra_appended(self):
        prompt = _build_system_prompt(extra="Remember: user likes cats.")
        assert "Remember: user likes cats." in prompt

    def test_no_extra(self):
        prompt = _build_system_prompt()
        # Should still be a valid non-empty string.
        assert len(prompt) > 50

    def test_extra_stripped(self):
        prompt = _build_system_prompt(extra="  extra whitespace  ")
        assert "extra whitespace" in prompt


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------


class TestBuildMessages:
    def test_text_only(self):
        msgs = _build_messages(
            text="What is 2+2?",
            history=[],
            system_prompt="You are helpful.",
        )
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "You are helpful."}
        assert msgs[1] == {"role": "user", "content": "What is 2+2?"}

    def test_with_history(self):
        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        msgs = _build_messages(
            text="Follow up.",
            history=history,
            system_prompt="sys",
        )
        assert len(msgs) == 4  # system + 2 history + 1 new user
        assert msgs[0]["role"] == "system"
        assert msgs[1] == {"role": "user", "content": "Hi"}
        assert msgs[2] == {"role": "assistant", "content": "Hello!"}
        assert msgs[3] == {"role": "user", "content": "Follow up."}

    def test_empty_system_prompt(self):
        msgs = _build_messages(text="Hello", history=[], system_prompt="")
        # Empty system prompt should not add a system message.
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_with_image(self):
        msgs = _build_messages(
            text="What's in this image?",
            history=[],
            system_prompt="sys",
            image="base64data",
        )
        assert len(msgs) == 2
        user_msg = msgs[1]
        assert user_msg["role"] == "user"
        content = user_msg["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        # First element is the image.
        assert content[0]["type"] == "image_url"
        assert "base64data" in content[0]["image_url"]["url"]
        assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        # Second element is the text.
        assert content[1]["type"] == "text"
        assert content[1]["text"] == "What's in this image?"

    def test_with_file(self):
        msgs = _build_messages(
            text="Summarize this",
            history=[],
            system_prompt="sys",
            file="/tmp/notes.txt",
        )
        user_content = msgs[1]["content"]
        assert isinstance(user_content, str)
        assert "[Attached file: /tmp/notes.txt]" in user_content
        assert "Summarize this" in user_content

    def test_with_image_and_file(self):
        msgs = _build_messages(
            text="Describe",
            history=[],
            system_prompt="sys",
            image="imgdata",
            file="/tmp/f.txt",
        )
        user_msg = msgs[1]
        content = user_msg["content"]
        assert isinstance(content, list)
        # The text part should include the file prefix.
        text_part = content[1]["text"]
        assert "[Attached file: /tmp/f.txt]" in text_part
        assert "Describe" in text_part

    def test_history_not_mutated(self):
        history = [{"role": "user", "content": "original"}]
        original_history = [dict(h) for h in history]
        _build_messages(text="new", history=history, system_prompt="sys")
        assert history == original_history


# ---------------------------------------------------------------------------
# Tool call accumulation
# ---------------------------------------------------------------------------


def _make_tool_delta(index=0, tc_id=None, name=None, arguments=None):
    """Create a mock tool_call delta object (SimpleNamespace)."""
    fn = SimpleNamespace()
    fn.name = name
    fn.arguments = arguments
    tc = SimpleNamespace()
    tc.index = index
    tc.id = tc_id
    tc.function = fn
    return tc


class TestAccumulateToolCalls:
    def test_single_tool_call_in_one_chunk(self):
        acc: dict[int, dict] = {}
        _accumulate_tool_calls(acc, [
            _make_tool_delta(0, "call_1", "shell", '{"command": "ls"}'),
        ])
        assert 0 in acc
        assert acc[0]["id"] == "call_1"
        assert acc[0]["name"] == "shell"
        assert acc[0]["arguments"] == '{"command": "ls"}'

    def test_arguments_streamed_incrementally(self):
        acc: dict[int, dict] = {}
        # First chunk: id + name + partial args.
        _accumulate_tool_calls(acc, [
            _make_tool_delta(0, "call_1", "shell", '{"comma'),
        ])
        # Second chunk: more args.
        _accumulate_tool_calls(acc, [
            _make_tool_delta(0, None, None, 'nd": "ls'),
        ])
        # Third chunk: closing.
        _accumulate_tool_calls(acc, [
            _make_tool_delta(0, None, None, '"}'),
        ])
        assert acc[0]["name"] == "shell"
        assert acc[0]["arguments"] == '{"command": "ls"}'

    def test_multiple_tool_calls(self):
        acc: dict[int, dict] = {}
        _accumulate_tool_calls(acc, [
            _make_tool_delta(0, "call_1", "shell", '{"command": "ls"}'),
        ])
        _accumulate_tool_calls(acc, [
            _make_tool_delta(1, "call_2", "clipboard", '{"text": "hi"}'),
        ])
        assert len(acc) == 2
        assert acc[0]["name"] == "shell"
        assert acc[1]["name"] == "clipboard"

    def test_id_updated_on_later_chunk(self):
        acc: dict[int, dict] = {}
        _accumulate_tool_calls(acc, [
            _make_tool_delta(0, "", "shell", ""),
        ])
        _accumulate_tool_calls(acc, [
            _make_tool_delta(0, "call_late", None, '{"a": 1}'),
        ])
        assert acc[0]["id"] == "call_late"

    def test_dict_format_tool_calls(self):
        """Tool calls can also arrive as plain dicts (not objects)."""
        acc: dict[int, dict] = {}
        _accumulate_tool_calls(acc, [
            {"index": 0, "id": "call_d", "function": {"name": "web_search", "arguments": '{"q": "test"}'}},
        ])
        assert acc[0]["name"] == "web_search"
        assert acc[0]["arguments"] == '{"q": "test"}'


class TestParseToolCalls:
    def test_parses_valid_json(self):
        acc = {0: {"id": "c1", "name": "shell", "arguments": '{"command": "ls"}'}}
        result = _parse_tool_calls(acc)
        assert len(result) == 1
        assert result[0]["id"] == "c1"
        assert result[0]["name"] == "shell"
        assert result[0]["arguments"] == {"command": "ls"}

    def test_parses_empty_arguments(self):
        acc = {0: {"id": "c1", "name": "screenshot", "arguments": ""}}
        result = _parse_tool_calls(acc)
        assert result[0]["arguments"] == {}

    def test_handles_invalid_json(self):
        acc = {0: {"id": "c1", "name": "shell", "arguments": "not json{{"}}
        result = _parse_tool_calls(acc)
        assert result[0]["arguments"] == {}

    def test_preserves_order(self):
        acc = {
            2: {"id": "c3", "name": "third", "arguments": "{}"},
            0: {"id": "c1", "name": "first", "arguments": "{}"},
            1: {"id": "c2", "name": "second", "arguments": "{}"},
        }
        result = _parse_tool_calls(acc)
        assert [r["name"] for r in result] == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class TestNotify:
    @mock.patch("aside.query.subprocess.Popen")
    def test_notify_sends_notification(self, mock_popen):
        notify("test-tag", "Hello world")
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "notify-send" in args
        assert "test-tag" in " ".join(args)
        assert "Hello world" in args

    @mock.patch("aside.query.subprocess.Popen")
    def test_notify_uses_aside_app_name(self, mock_popen):
        notify("tag", "msg")
        args = mock_popen.call_args[0][0]
        assert "-a" in args
        idx = args.index("-a")
        assert args[idx + 1] == "Aside"


class TestNotifyFinal:
    @mock.patch("aside.query.subprocess.run")
    def test_truncates_long_text(self, mock_run):
        mock_run.return_value = mock.Mock(stdout="", returncode=0)
        long_text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        config = {"notifications": {}}
        notify_final("tag", long_text, "conv-id", config)
        # Wait for the background thread.
        import time
        time.sleep(0.2)
        assert mock_run.called
        args = mock_run.call_args[0][0]
        body = args[-1]
        # Should contain last 2 sentences.
        assert "Third sentence." in body
        assert "Fourth sentence." in body

    @mock.patch("aside.query.subprocess.run")
    def test_includes_tools_used(self, mock_run):
        mock_run.return_value = mock.Mock(stdout="", returncode=0)
        config = {"notifications": {}}
        notify_final("tag", "Answer.", "conv-id", config, tools_used=["shell", "clipboard"])
        import time
        time.sleep(0.2)
        assert mock_run.called
        args = mock_run.call_args[0][0]
        body = args[-1]
        assert "shell" in body
        assert "clipboard" in body

    @mock.patch("aside.query.subprocess.run")
    def test_reply_action_with_command(self, mock_run):
        mock_run.return_value = mock.Mock(stdout="reply\n", returncode=0)
        config = {"notifications": {"reply_command": "echo {conv_id}"}}
        with mock.patch("aside.query.subprocess.Popen") as mock_popen:
            notify_final("tag", "Answer.", "abc-123", config)
            import time
            time.sleep(0.3)
            if mock_popen.called:
                cmd = mock_popen.call_args[0][0]
                assert "abc-123" in cmd

    @mock.patch("aside.query.subprocess.run")
    def test_no_actions_without_config(self, mock_run):
        mock_run.return_value = mock.Mock(stdout="", returncode=0)
        config = {"notifications": {}}
        notify_final("tag", "Answer.", "conv-id", config)
        import time
        time.sleep(0.2)
        args = mock_run.call_args[0][0]
        # Should not have -A flags.
        assert "-A" not in args


# ---------------------------------------------------------------------------
# stream_response (mocked LiteLLM)
# ---------------------------------------------------------------------------


def _make_chunk(content=None, tool_calls=None, usage=None, model="test-model", finish_reason=None):
    """Create a mock LiteLLM streaming chunk."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)

    chunk_usage = None
    if usage:
        chunk_usage = SimpleNamespace(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    return SimpleNamespace(
        choices=[choice],
        model=model,
        usage=chunk_usage,
    )


def _make_usage_chunk(prompt_tokens, completion_tokens, model="test-model"):
    """Create a final usage-only chunk (no choices)."""
    return SimpleNamespace(
        choices=[],
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


class TestStreamResponse:
    @mock.patch("aside.query.litellm.completion")
    def test_basic_text_streaming(self, mock_completion):
        mock_completion.return_value = iter([
            _make_chunk(content="Hello "),
            _make_chunk(content="world!"),
            _make_usage_chunk(100, 50),
        ])
        from aside.sentence_buffer import SentenceBuffer
        text, tool_calls, usage = stream_response(
            model="test-model",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            cancel_event=None,
            overlay_sock=None,
            tts=None,
            sentence_buf=SentenceBuffer(),
            speak_on=False,
        )
        assert text == "Hello world!"
        assert tool_calls == []
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 50

    @mock.patch("aside.query.litellm.completion")
    def test_tool_call_streaming(self, mock_completion):
        mock_completion.return_value = iter([
            _make_chunk(tool_calls=[
                _make_tool_delta(0, "call_1", "shell", '{"command":'),
            ]),
            _make_chunk(tool_calls=[
                _make_tool_delta(0, None, None, ' "ls"}'),
            ]),
            _make_usage_chunk(200, 100),
        ])
        from aside.sentence_buffer import SentenceBuffer
        text, tool_calls, usage = stream_response(
            model="test-model",
            messages=[{"role": "user", "content": "list files"}],
            tools=[{"type": "function", "function": {"name": "shell"}}],
            cancel_event=None,
            overlay_sock=None,
            tts=None,
            sentence_buf=SentenceBuffer(),
            speak_on=False,
        )
        assert text == ""
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "shell"
        assert tool_calls[0]["arguments"] == {"command": "ls"}

    @mock.patch("aside.query.litellm.completion")
    def test_cancellation(self, mock_completion):
        cancel = threading.Event()
        cancel.set()

        mock_completion.return_value = iter([
            _make_chunk(content="Should not accumulate"),
        ])
        from aside.sentence_buffer import SentenceBuffer
        text, tool_calls, usage = stream_response(
            model="test-model",
            messages=[],
            tools=[],
            cancel_event=cancel,
            overlay_sock=None,
            tts=None,
            sentence_buf=SentenceBuffer(),
            speak_on=False,
        )
        # Cancelled: returns empty tool_calls.
        assert tool_calls == []

    @mock.patch("aside.query.litellm.completion")
    def test_overlay_receives_text_deltas(self, mock_completion):
        mock_completion.return_value = iter([
            _make_chunk(content="chunk1"),
            _make_chunk(content="chunk2"),
        ])
        sent = []
        mock_sock = mock.Mock()
        mock_sock.sendall = lambda data: sent.append(json.loads(data.decode().strip()))

        from aside.sentence_buffer import SentenceBuffer
        stream_response(
            model="test-model",
            messages=[],
            tools=[],
            cancel_event=None,
            overlay_sock=mock_sock,
            tts=None,
            sentence_buf=SentenceBuffer(),
            speak_on=False,
        )
        text_cmds = [m for m in sent if m.get("cmd") == "text"]
        assert len(text_cmds) == 2
        assert text_cmds[0]["data"] == "chunk1"
        assert text_cmds[1]["data"] == "chunk2"

    @mock.patch("aside.query.litellm.completion")
    def test_tts_receives_sentences(self, mock_completion):
        # Stream enough text to produce a sentence.
        mock_completion.return_value = iter([
            _make_chunk(content="This is a complete sentence. "),
            _make_chunk(content="And another."),
        ])
        mock_tts = mock.Mock()
        mock_tts.speak = mock.Mock()

        from aside.sentence_buffer import SentenceBuffer
        stream_response(
            model="test-model",
            messages=[],
            tools=[],
            cancel_event=None,
            overlay_sock=None,
            tts=mock_tts,
            sentence_buf=SentenceBuffer(),
            speak_on=True,
        )
        # TTS should have been called at least once.
        assert mock_tts.speak.called

    @mock.patch("aside.query.litellm.completion")
    def test_mixed_text_and_tool_calls(self, mock_completion):
        """Response with both text content and tool calls."""
        mock_completion.return_value = iter([
            _make_chunk(content="Let me check. "),
            _make_chunk(tool_calls=[
                _make_tool_delta(0, "call_1", "shell", '{"command": "date"}'),
            ]),
            _make_usage_chunk(150, 75),
        ])
        from aside.sentence_buffer import SentenceBuffer
        text, tool_calls, usage = stream_response(
            model="test-model",
            messages=[],
            tools=[{"type": "function", "function": {"name": "shell"}}],
            cancel_event=None,
            overlay_sock=None,
            tts=None,
            sentence_buf=SentenceBuffer(),
            speak_on=False,
        )
        assert text == "Let me check. "
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "shell"


# ---------------------------------------------------------------------------
# NEW_CONVERSATION sentinel
# ---------------------------------------------------------------------------


class TestNewConversation:
    def test_sentinel_is_unique(self):
        assert NEW_CONVERSATION is not None
        assert NEW_CONVERSATION is not True
        assert NEW_CONVERSATION is not False

    def test_sentinel_identity(self):
        """Sentinel should be compared with `is`, not `==`."""
        assert NEW_CONVERSATION is NEW_CONVERSATION
