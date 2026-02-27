"""Tests for aside.voice -- voice input module.

These tests exercise the pure-logic components (SpeechEndDetector,
VoiceListener construction) without importing heavy ML dependencies
(openwakeword, faster-whisper, webrtcvad).
"""

from pathlib import Path
from unittest import mock

import pytest


def _import_speech_detector():
    """Import SpeechEndDetector from the package directory."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "aside.voice.speech_detector",
        Path(__file__).parent.parent / "aside" / "voice" / "speech_detector.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _import_listener():
    """Import the listener module from the package directory."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "aside.voice.listener",
        Path(__file__).parent.parent / "aside" / "voice" / "listener.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# SpeechEndDetector
# ---------------------------------------------------------------------------


class TestSpeechEndDetector:
    """Verify silence detection, smart silence, and force-send logic."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.mod = _import_speech_detector()
        self.SpeechEndDetector = self.mod.SpeechEndDetector

    # -- Construction --

    def test_default_construction(self):
        d = self.SpeechEndDetector()
        assert d.silence_timeout == 2.5
        assert d.smart_silence is True
        assert d.force_send_phrases == []

    def test_custom_construction(self):
        d = self.SpeechEndDetector(
            silence_timeout=3.0,
            smart_silence=False,
            force_send_phrases=["Send It", "done"],
        )
        assert d.silence_timeout == 3.0
        assert d.smart_silence is False
        assert d.force_send_phrases == ["send it", "done"]

    # -- Effective timeout --

    def test_default_timeout_no_transcript(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        assert d._effective_timeout() == 2.5

    def test_smart_silence_off(self):
        d = self.SpeechEndDetector(silence_timeout=2.5, smart_silence=False)
        d.update_transcript("hello world.")
        assert d._effective_timeout() == 2.5

    def test_sentence_ending_shortens_timeout(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        d.update_transcript("What is the weather?")
        assert d._effective_timeout() == 1.5

    def test_sentence_ending_period(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        d.update_transcript("Do this thing.")
        assert d._effective_timeout() == 1.5

    def test_sentence_ending_exclamation(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        d.update_transcript("Wow!")
        assert d._effective_timeout() == 1.5

    def test_mid_sentence_word_extends_timeout(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        d.update_transcript("search for the")
        assert d._effective_timeout() == 3.5

    def test_mid_sentence_conjunction(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        d.update_transcript("apples and")
        assert d._effective_timeout() == 3.5

    def test_normal_word_uses_default(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        d.update_transcript("hello world")
        assert d._effective_timeout() == 2.5

    def test_empty_transcript_uses_default(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        d.update_transcript("   ")
        assert d._effective_timeout() == 2.5

    # -- is_done --

    def test_is_done_below_timeout(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        assert d.is_done(2.0) is False

    def test_is_done_at_timeout(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        assert d.is_done(2.5) is True

    def test_is_done_above_timeout(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        assert d.is_done(3.0) is True

    # -- on_speech_start resets transcript --

    def test_on_speech_start_resets(self):
        d = self.SpeechEndDetector(silence_timeout=2.5)
        d.update_transcript("hello world.")
        assert d._effective_timeout() == 1.5
        d.on_speech_start()
        assert d._effective_timeout() == 2.5  # back to default

    # -- Force-send phrases --

    def test_force_send_match(self):
        d = self.SpeechEndDetector(force_send_phrases=["send it"])
        d.update_transcript("what is the weather send it")
        assert d.check_force_send() == "send it"

    def test_force_send_no_match(self):
        d = self.SpeechEndDetector(force_send_phrases=["send it"])
        d.update_transcript("what is the weather")
        assert d.check_force_send() is None

    def test_force_send_whole_text(self):
        d = self.SpeechEndDetector(force_send_phrases=["send it"])
        d.update_transcript("send it")
        assert d.check_force_send() == "send it"

    def test_force_send_not_partial_word(self):
        """'resend it' should NOT match 'send it' (no space before)."""
        d = self.SpeechEndDetector(force_send_phrases=["send it"])
        d.update_transcript("resend it")
        assert d.check_force_send() is None

    def test_force_send_empty_transcript(self):
        d = self.SpeechEndDetector(force_send_phrases=["send it"])
        assert d.check_force_send() is None

    def test_force_send_case_insensitive(self):
        d = self.SpeechEndDetector(force_send_phrases=["send it"])
        d.update_transcript("Hello SEND IT")
        assert d.check_force_send() == "send it"

    # -- strip_force_phrase --

    def test_strip_force_phrase(self):
        result = self.SpeechEndDetector.strip_force_phrase(
            "what is the weather send it", "send it"
        )
        assert result == "what is the weather"

    def test_strip_force_phrase_case_insensitive(self):
        result = self.SpeechEndDetector.strip_force_phrase(
            "Hello World SEND IT", "send it"
        )
        assert result == "Hello World"

    def test_strip_force_phrase_not_found(self):
        result = self.SpeechEndDetector.strip_force_phrase(
            "hello world", "send it"
        )
        assert result == "hello world"

    def test_strip_force_phrase_trailing_whitespace(self):
        result = self.SpeechEndDetector.strip_force_phrase(
            "query text send it   ", "send it"
        )
        assert result == "query text"


# ---------------------------------------------------------------------------
# VoiceListener construction
# ---------------------------------------------------------------------------


class TestVoiceListenerConstruction:
    """Verify VoiceListener can be built with a config dict.

    These tests must NOT trigger import of heavy ML deps (openwakeword,
    faster-whisper, webrtcvad) -- only the listener module itself.
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.mod = _import_listener()
        self.VoiceListener = self.mod.VoiceListener

    def _make_config(self, **overrides):
        cfg = {
            "wake_word_model": "~/.local/share/models/hey_jarvis.onnx",
            "wake_word_threshold": 0.6,
            "pre_roll_seconds": 0.5,
            "stt_model": "small",
            "stt_device": "cpu",
            "smart_silence": True,
            "silence_timeout": 2.5,
            "no_speech_timeout": 3.0,
            "force_send_phrases": ["send it"],
        }
        cfg.update(overrides)
        return cfg

    def test_construction_stores_config(self):
        cfg = self._make_config()
        vl = self.VoiceListener(cfg)
        assert vl._config is cfg

    def test_whisper_config_from_voice_config(self):
        cfg = self._make_config(stt_model="large", stt_device="cuda")
        vl = self.VoiceListener(cfg)
        assert vl._whisper_config == {"model": "large", "device": "cuda"}

    def test_components_not_loaded_at_construction(self):
        """Heavy deps should be lazy-loaded, not at __init__ time."""
        cfg = self._make_config()
        vl = self.VoiceListener(cfg)
        assert vl._audio is None
        assert vl._wake_word is None
        assert vl._detector is None

    def test_request_listen(self):
        cfg = self._make_config()
        vl = self.VoiceListener(cfg)
        vl.request_listen("conv-123")
        req = vl._check_listen_request()
        assert req == {"conversation_id": "conv-123"}

    def test_request_listen_consumed(self):
        cfg = self._make_config()
        vl = self.VoiceListener(cfg)
        vl.request_listen("conv-123")
        vl._check_listen_request()
        assert vl._check_listen_request() is None

    def test_set_muted(self):
        cfg = self._make_config()
        vl = self.VoiceListener(cfg)
        assert vl._muted is False
        vl.set_muted(True)
        assert vl._muted is True
        vl.set_muted(False)
        assert vl._muted is False

    def test_default_stt_values(self):
        """Config with no stt_model/stt_device uses defaults."""
        cfg = {"wake_word_model": "/some/model.onnx"}
        vl = self.VoiceListener(cfg)
        assert vl._whisper_config == {"model": "base", "device": "cpu"}


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------


class TestNotificationHelpers:
    """Verify notification functions call notify-send correctly."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.mod = _import_listener()

    @mock.patch("subprocess.Popen")
    def test_notify_listening(self, mock_popen):
        self.mod.notify_listening()
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "notify-send" in args
        assert "Listening..." in args
        assert "aside-voice" in " ".join(args)

    @mock.patch("subprocess.Popen")
    def test_notify_transcription(self, mock_popen):
        self.mod.notify_transcription("hello world")
        args = mock_popen.call_args[0][0]
        assert "hello world" in args

    @mock.patch("subprocess.Popen")
    def test_notify_transcription_fallback(self, mock_popen):
        self.mod.notify_transcription(None)
        args = mock_popen.call_args[0][0]
        assert "Listening..." in args

    @mock.patch("subprocess.Popen")
    def test_notify_dismiss(self, mock_popen):
        self.mod.notify_dismiss()
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "-t" in args
        idx = args.index("-t")
        assert args[idx + 1] == "1"
