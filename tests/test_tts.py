"""Tests for the TTS pipeline.

These tests do NOT require piper-tts or sounddevice installed.
They verify the pipeline's state management and API contracts.
"""

from aside.tts import TTSPipeline


class TestConstruction:
    """TTSPipeline can be created without loading piper."""

    def test_default_construction(self):
        p = TTSPipeline()
        assert p._model_path == TTSPipeline._DEFAULT_MODEL
        assert p._speed == 1.0
        assert p._voice is None  # piper not loaded

    def test_custom_construction(self):
        p = TTSPipeline(model="/tmp/voice.onnx", speed=1.5)
        assert p._model_path == "/tmp/voice.onnx"
        assert p._speed == 1.5
        assert p._voice is None


class TestUpdateConfig:
    """update_config changes internal state."""

    def test_updates_speed(self):
        p = TTSPipeline()
        p.update_config(model="", speed=1.5)
        assert p._speed == 1.5

    def test_model_change_clears_voice(self):
        p = TTSPipeline()
        p._voice = "fake-loaded-voice"
        p.update_config(model="/tmp/new.onnx", speed=1.0)
        assert p._model_path == "/tmp/new.onnx"
        assert p._voice is None  # cleared for reload

    def test_same_model_keeps_voice(self):
        p = TTSPipeline(model="/tmp/voice.onnx")
        p._voice = "fake-loaded-voice"
        p.update_config(model="/tmp/voice.onnx", speed=1.5)
        assert p._voice == "fake-loaded-voice"  # not cleared


class TestRunningFlag:
    """_running starts as False."""

    def test_initial_state(self):
        p = TTSPipeline()
        assert p._running is False

    def test_threads_not_created(self):
        p = TTSPipeline()
        assert p._synth_thread is None
        assert p._play_thread is None


class TestSafeWhenNotStarted:
    """speak/stop/finish don't crash when pipeline is not started."""

    def test_speak_noop(self):
        p = TTSPipeline()
        p.speak("Hello world")  # should not raise

    def test_stop_noop(self):
        p = TTSPipeline()
        p.stop()  # should not raise

    def test_finish_noop(self):
        p = TTSPipeline()
        p.finish()  # should not raise

    def test_wait_done_returns_immediately(self):
        p = TTSPipeline()
        result = p.wait_done(timeout=1)
        assert result is True  # no thread to wait for
