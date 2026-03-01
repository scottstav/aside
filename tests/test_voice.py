"""Tests for aside.voice -- voice input module.

These tests exercise the pure-logic components (SpeechEndDetector)
and the capture_one_shot function (with mocked audio/STT deps).
"""

import sys
from pathlib import Path
from types import ModuleType
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
# capture_one_shot
# ---------------------------------------------------------------------------


class TestCaptureOneShot:
    """Verify capture_one_shot records, transcribes, and returns text.

    All audio/STT deps are mocked -- these tests verify the control flow
    without needing a real microphone, numpy, or Whisper model.
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.mod = _import_listener()
        self.capture_one_shot = self.mod.capture_one_shot

    def _make_config(self, **overrides):
        cfg = {
            "stt_model": "base",
            "stt_device": "cpu",
            "smart_silence": True,
            "silence_timeout": 2.5,
            "no_speech_timeout": 3.0,
            "force_send_phrases": [],
        }
        cfg.update(overrides)
        return cfg

    def test_capture_one_shot_is_importable(self):
        """capture_one_shot should be importable from aside.voice.listener."""
        from aside.voice.listener import capture_one_shot as fn
        assert callable(fn)

    def test_capture_one_shot_calls_audio_start_stop(self):
        """capture_one_shot should start and stop the audio pipeline."""
        mock_audio = mock.MagicMock()

        with (
            mock.patch.dict(
                "sys.modules",
                {
                    "aside.voice.audio": mock.MagicMock(
                        AudioPipeline=mock.MagicMock(return_value=mock_audio),
                        RATE=16000,
                        VAD_FRAME_MS=30,
                    ),
                    "aside.voice.speech_detector": mock.MagicMock(),
                    "aside.voice.stt": mock.MagicMock(),
                },
            ),
            mock.patch.object(
                self.mod, "_do_capture", return_value="test"
            ),
        ):
            result = self.mod.capture_one_shot(self._make_config())

        assert result == "test"
        mock_audio.start.assert_called_once()
        mock_audio.stop.assert_called_once()

    def test_capture_one_shot_stops_audio_on_exception(self):
        """Audio pipeline should be stopped even if _do_capture raises."""
        mock_audio = mock.MagicMock()

        with (
            mock.patch.dict(
                "sys.modules",
                {
                    "aside.voice.audio": mock.MagicMock(
                        AudioPipeline=mock.MagicMock(return_value=mock_audio),
                        RATE=16000,
                        VAD_FRAME_MS=30,
                    ),
                    "aside.voice.speech_detector": mock.MagicMock(),
                    "aside.voice.stt": mock.MagicMock(),
                },
            ),
            mock.patch.object(
                self.mod, "_do_capture",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(RuntimeError),
        ):
            self.mod.capture_one_shot(self._make_config())

        mock_audio.start.assert_called_once()
        mock_audio.stop.assert_called_once()

    def test_do_capture_returns_text_on_silence_timeout(self):
        """_do_capture should return transcribed text when silence timeout fires."""
        # Create mock objects for audio and detector
        mock_audio = mock.MagicMock()
        mock_audio.read_vad_frame.return_value = (b"\x00" * 960, False)

        # Mock get_captured_audio to return a mock with len > 0
        mock_captured = mock.MagicMock()
        mock_captured.__len__ = mock.MagicMock(return_value=8000)
        mock_audio.get_captured_audio.return_value = mock_captured

        # Mock end_capture to return something with len >= RATE * 0.3
        mock_final = mock.MagicMock()
        mock_final.__len__ = mock.MagicMock(return_value=8000)
        mock_audio.end_capture.return_value = mock_final

        mock_detector = mock.MagicMock()
        mock_detector.is_done.return_value = True  # silence timeout immediately
        mock_detector.check_force_send.return_value = None

        # Mock time and transcribe
        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            return 100.0 + call_count[0] * 0.03

        # Create mock modules for the lazy imports inside _do_capture
        mock_audio_mod = mock.MagicMock()
        mock_audio_mod.RATE = 16000
        mock_audio_mod.VAD_FRAME_MS = 30

        mock_stt_mod = mock.MagicMock()
        mock_stt_mod.transcribe.return_value = "hello world"

        mock_sed_mod = mock.MagicMock()

        with (
            mock.patch.dict(
                "sys.modules",
                {
                    "aside.voice.audio": mock_audio_mod,
                    "aside.voice.stt": mock_stt_mod,
                    "aside.voice.speech_detector": mock_sed_mod,
                },
            ),
            mock.patch.object(self.mod, "time") as mock_time,
        ):
            mock_time.monotonic = fake_monotonic
            result = self.mod._do_capture(
                mock_audio,
                mock_detector,
                {"model": "base", "device": "cpu"},
                self._make_config(),
            )

        assert result == "hello world"

    def test_do_capture_returns_empty_on_no_speech(self):
        """_do_capture should return '' when no speech before timeout."""
        mock_audio = mock.MagicMock()
        mock_audio.read_vad_frame.return_value = (b"\x00" * 960, False)

        mock_captured = mock.MagicMock()
        mock_captured.__len__ = mock.MagicMock(return_value=4800)
        mock_audio.get_captured_audio.return_value = mock_captured
        mock_audio.end_capture.return_value = mock.MagicMock()

        mock_detector = mock.MagicMock()
        mock_detector.is_done.return_value = False
        mock_detector.check_force_send.return_value = None

        # Time: after first 2s window, jump past no_speech_timeout
        times = iter([0.0, 0.0] + [3.1] * 100)

        mock_audio_mod = mock.MagicMock()
        mock_audio_mod.RATE = 16000
        mock_audio_mod.VAD_FRAME_MS = 30

        mock_stt_mod = mock.MagicMock()
        mock_stt_mod.transcribe.return_value = ""  # no speech detected

        with (
            mock.patch.dict(
                "sys.modules",
                {
                    "aside.voice.audio": mock_audio_mod,
                    "aside.voice.stt": mock_stt_mod,
                    "aside.voice.speech_detector": mock.MagicMock(),
                },
            ),
            mock.patch.object(self.mod, "time") as mock_time,
        ):
            mock_time.monotonic = mock.MagicMock(side_effect=times)
            result = self.mod._do_capture(
                mock_audio,
                mock_detector,
                {"model": "base", "device": "cpu"},
                self._make_config(no_speech_timeout=3.0),
            )

        assert result == ""

    def test_do_capture_returns_empty_on_short_audio(self):
        """Audio shorter than 0.3s should be discarded and return ''."""
        mock_audio = mock.MagicMock()
        mock_audio.read_vad_frame.return_value = (b"\x00" * 960, True)

        mock_captured = mock.MagicMock()
        mock_captured.__len__ = mock.MagicMock(return_value=8000)
        mock_audio.get_captured_audio.return_value = mock_captured

        # end_capture returns audio shorter than RATE * 0.3 = 4800
        mock_final = mock.MagicMock()
        mock_final.__len__ = mock.MagicMock(return_value=100)
        mock_audio.end_capture.return_value = mock_final

        mock_detector = mock.MagicMock()
        mock_detector.is_done.return_value = True
        mock_detector.check_force_send.return_value = None

        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            return 100.0 + call_count[0] * 0.03

        mock_audio_mod = mock.MagicMock()
        mock_audio_mod.RATE = 16000
        mock_audio_mod.VAD_FRAME_MS = 30

        mock_stt_mod = mock.MagicMock()
        mock_stt_mod.transcribe.return_value = "hello"

        with (
            mock.patch.dict(
                "sys.modules",
                {
                    "aside.voice.audio": mock_audio_mod,
                    "aside.voice.stt": mock_stt_mod,
                    "aside.voice.speech_detector": mock.MagicMock(),
                },
            ),
            mock.patch.object(self.mod, "time") as mock_time,
        ):
            mock_time.monotonic = fake_monotonic
            result = self.mod._do_capture(
                mock_audio,
                mock_detector,
                {"model": "base", "device": "cpu"},
                self._make_config(),
            )

        assert result == ""

    def test_do_capture_returns_empty_on_exception(self):
        """If an exception occurs during frame reading, return ''."""
        mock_audio = mock.MagicMock()
        mock_audio.read_vad_frame.side_effect = IOError("stream ended")
        mock_audio.end_capture = mock.MagicMock()

        mock_detector = mock.MagicMock()

        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            return 100.0 + call_count[0] * 0.03

        mock_audio_mod = mock.MagicMock()
        mock_audio_mod.RATE = 16000
        mock_audio_mod.VAD_FRAME_MS = 30

        with (
            mock.patch.dict(
                "sys.modules",
                {
                    "aside.voice.audio": mock_audio_mod,
                    "aside.voice.stt": mock.MagicMock(),
                    "aside.voice.speech_detector": mock.MagicMock(),
                },
            ),
            mock.patch.object(self.mod, "time") as mock_time,
        ):
            mock_time.monotonic = fake_monotonic
            result = self.mod._do_capture(
                mock_audio,
                mock_detector,
                {"model": "base", "device": "cpu"},
                self._make_config(),
            )

        assert result == ""
        mock_audio.end_capture.assert_called_once()

    def test_do_capture_force_send_returns_stripped_text(self):
        """When force-send phrase detected, return text with phrase stripped."""
        mock_audio = mock.MagicMock()
        mock_audio.read_vad_frame.return_value = (b"\x00" * 960, True)

        mock_captured = mock.MagicMock()
        mock_captured.__len__ = mock.MagicMock(return_value=8000)
        mock_audio.get_captured_audio.return_value = mock_captured

        mock_final = mock.MagicMock()
        mock_final.__len__ = mock.MagicMock(return_value=8000)
        mock_audio.end_capture.return_value = mock_final

        mock_detector = mock.MagicMock()
        mock_detector.is_done.return_value = False
        mock_detector.check_force_send.return_value = "send it"

        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            return 100.0 + call_count[0] * 0.03

        mock_audio_mod = mock.MagicMock()
        mock_audio_mod.RATE = 16000
        mock_audio_mod.VAD_FRAME_MS = 30

        mock_stt_mod = mock.MagicMock()
        mock_stt_mod.transcribe.return_value = "what is the weather send it"

        mock_sed_mod = mock.MagicMock()
        mock_sed_class = mock.MagicMock()
        mock_sed_class.strip_force_phrase.return_value = "what is the weather"
        mock_sed_mod.SpeechEndDetector = mock_sed_class

        with (
            mock.patch.dict(
                "sys.modules",
                {
                    "aside.voice.audio": mock_audio_mod,
                    "aside.voice.stt": mock_stt_mod,
                    "aside.voice.speech_detector": mock_sed_mod,
                },
            ),
            mock.patch.object(self.mod, "time") as mock_time,
        ):
            mock_time.monotonic = fake_monotonic
            result = self.mod._do_capture(
                mock_audio,
                mock_detector,
                {"model": "base", "device": "cpu"},
                self._make_config(force_send_phrases=["send it"]),
            )

        assert result == "what is the weather"

    def test_do_capture_empty_transcription_returns_empty(self):
        """If final transcription is empty/whitespace, return ''."""
        mock_audio = mock.MagicMock()
        mock_audio.read_vad_frame.return_value = (b"\x00" * 960, True)

        mock_captured = mock.MagicMock()
        mock_captured.__len__ = mock.MagicMock(return_value=8000)
        mock_audio.get_captured_audio.return_value = mock_captured

        mock_final = mock.MagicMock()
        mock_final.__len__ = mock.MagicMock(return_value=8000)
        mock_audio.end_capture.return_value = mock_final

        mock_detector = mock.MagicMock()
        mock_detector.is_done.return_value = True
        mock_detector.check_force_send.return_value = None

        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            return 100.0 + call_count[0] * 0.03

        mock_audio_mod = mock.MagicMock()
        mock_audio_mod.RATE = 16000
        mock_audio_mod.VAD_FRAME_MS = 30

        mock_stt_mod = mock.MagicMock()
        mock_stt_mod.transcribe.return_value = "   "  # whitespace only

        with (
            mock.patch.dict(
                "sys.modules",
                {
                    "aside.voice.audio": mock_audio_mod,
                    "aside.voice.stt": mock_stt_mod,
                    "aside.voice.speech_detector": mock.MagicMock(),
                },
            ),
            mock.patch.object(self.mod, "time") as mock_time,
        ):
            mock_time.monotonic = fake_monotonic
            result = self.mod._do_capture(
                mock_audio,
                mock_detector,
                {"model": "base", "device": "cpu"},
                self._make_config(),
            )

        assert result == ""
