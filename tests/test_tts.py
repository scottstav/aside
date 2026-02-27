"""Tests for the TTS pipeline.

These tests do NOT require kokoro or sounddevice installed.
They verify the pipeline's state management and API contracts.
"""

from aside.tts import TTSPipeline


class TestConstruction:
    """TTSPipeline can be created without loading kokoro."""

    def test_default_construction(self):
        p = TTSPipeline()
        assert p._model_name == "af_heart"
        assert p._speed == 1.0
        assert p._lang == "a"
        assert p._pipeline is None  # kokoro not loaded

    def test_custom_construction(self):
        p = TTSPipeline(model="bf_emma", speed=1.5, lang="b")
        assert p._model_name == "bf_emma"
        assert p._speed == 1.5
        assert p._lang == "b"
        assert p._pipeline is None


class TestUpdateConfig:
    """update_config changes internal state."""

    def test_updates_model_and_speed(self):
        p = TTSPipeline()
        p.update_config(model="bf_emma", speed=1.5, lang="a")
        assert p._model_name == "bf_emma"
        assert p._speed == 1.5

    def test_lang_change_clears_pipeline(self):
        p = TTSPipeline()
        p._pipeline = "fake-loaded-pipeline"
        p.update_config(model="af_heart", speed=1.0, lang="b")
        assert p._lang == "b"
        assert p._pipeline is None  # cleared for reload

    def test_same_lang_keeps_pipeline(self):
        p = TTSPipeline()
        p._pipeline = "fake-loaded-pipeline"
        p.update_config(model="bf_emma", speed=1.5, lang="a")
        assert p._pipeline == "fake-loaded-pipeline"  # not cleared


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
