"""TTS pipeline: Piper synthesis + sounddevice playback.

Manages two threads: one for synthesis (sentence -> audio), one for
playback (audio -> speakers). Supports interruption and lazy model loading.
"""

import logging
import queue
import threading
import time

import numpy as np

log = logging.getLogger("aside")

# Sentinel to signal threads to stop
_STOP = object()
_DONE = object()


class TTSPipeline:
    """Piper TTS synthesis and audio playback pipeline."""

    # Default voice: piper-voices-en-us package installs here
    _DEFAULT_MODEL = "/usr/share/piper-voices/en/en_US/lessac/medium/en_US-lessac-medium.onnx"

    def __init__(self, model="", speed=1.0):
        self._model_path = model or self._DEFAULT_MODEL
        self._speed = speed
        self._voice = None  # Lazy-loaded PiperVoice
        self._sample_rate = 22050  # Updated when voice loads
        self._sentence_q: queue.Queue = queue.Queue()
        self._audio_q: queue.Queue = queue.Queue()
        self._synth_thread: threading.Thread | None = None
        self._play_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        """Lazy-load the Piper voice model on first use."""
        if self._voice is not None:
            return
        if not self._model_path:
            raise ValueError("No Piper model configured — set tts.model in config.toml")
        log.info("Loading Piper TTS model: %s ...", self._model_path)
        try:
            from piper import PiperVoice
            self._voice = PiperVoice.load(self._model_path)
            self._sample_rate = self._voice.config.sample_rate
            log.info("Piper TTS loaded (sample_rate=%d)", self._sample_rate)
        except Exception:
            log.exception("Failed to load Piper TTS")
            raise

    def update_config(self, model: str, speed: float):
        """Update voice settings. Takes effect on next sentence."""
        if model != self._model_path:
            self._model_path = model
            self._voice = None  # Force reload for new model
        self._speed = speed

    def start(self):
        """Start the synthesis and playback threads."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._sentence_q = queue.Queue()
            self._audio_q = queue.Queue()
            self._synth_thread = threading.Thread(target=self._synth_loop, daemon=True)
            self._play_thread = threading.Thread(target=self._play_loop, daemon=True)
            self._synth_thread.start()
            self._play_thread.start()

    def stop(self):
        """Stop threads and clear queues. Kills current playback."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        # Clear queues and send stop sentinels
        self._drain_queue(self._sentence_q)
        self._drain_queue(self._audio_q)
        self._sentence_q.put(_STOP)
        self._audio_q.put(_STOP)

        # Kill current audio playback
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

        # Wait briefly for threads to notice the stop signal.
        # Don't null references -- wait_done() may be polling them concurrently.
        if self._synth_thread:
            self._synth_thread.join(timeout=2)
        if self._play_thread:
            self._play_thread.join(timeout=2)

    def speak(self, sentence: str):
        """Queue a sentence for synthesis and playback."""
        if self._running:
            self._sentence_q.put(sentence)

    def finish(self):
        """Signal that no more sentences are coming."""
        if self._running:
            self._sentence_q.put(_DONE)

    def wait_done(self, timeout=120):
        """Wait for playback to complete. Returns True if done, False if timeout."""
        deadline = time.monotonic() + timeout
        while True:
            thread = self._play_thread
            if thread is None or not thread.is_alive():
                return True
            if not self._running:
                return True  # stop() was called, don't wait further
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            thread.join(timeout=min(remaining, 0.5))

    def _synth_loop(self):
        """Thread: pull sentences, synthesize with Piper, push audio."""
        try:
            self._ensure_loaded()
        except Exception:
            self._audio_q.put(_STOP)
            return

        from piper import SynthesisConfig

        # Piper speed: length_scale < 1 = faster, > 1 = slower
        # Our speed: > 1 = faster, so invert
        length_scale = 1.0 / self._speed if self._speed > 0 else 1.0
        syn_cfg = SynthesisConfig(length_scale=length_scale)

        while True:
            item = self._sentence_q.get()
            if item is _STOP:
                self._audio_q.put(_STOP)
                break
            if item is _DONE:
                self._audio_q.put(_DONE)
                break
            try:
                for chunk in self._voice.synthesize(item, syn_config=syn_cfg):
                    if not self._running:
                        break
                    self._audio_q.put(chunk.audio_float_array)
            except Exception:
                log.exception("TTS synthesis error for: %s", item[:50])

    def _play_loop(self):
        """Thread: pull audio arrays, play through speakers."""
        import sounddevice as sd

        # Use the PipeWire device so audio follows the user's default
        # sink (just like every other app).
        pw_dev = None
        for i, d in enumerate(sd.query_devices()):
            if d["name"] == "pipewire" and d["max_output_channels"] > 0:
                pw_dev = i
                break

        while True:
            item = self._audio_q.get()
            if item is _STOP or item is _DONE:
                break
            if not self._running:
                break
            try:
                sd.play(item, samplerate=self._sample_rate, device=pw_dev)
                # Poll _running during playback so stop() can interrupt us
                # without relying on cross-thread sd.stop() (unreliable with PipeWire)
                stream = sd.get_stream()
                while stream and stream.active:
                    if not self._running:
                        sd.stop()
                        break
                    time.sleep(0.05)
            except Exception:
                log.exception("Audio playback error")

    @staticmethod
    def _drain_queue(q):
        """Empty a queue without blocking."""
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break
