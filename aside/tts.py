"""TTS pipeline: Kokoro synthesis + sounddevice playback.

Manages two threads: one for synthesis (sentence -> audio), one for
playback (audio -> speakers). Supports interruption and lazy model loading.
"""

import logging
import queue
import threading
import time

log = logging.getLogger("aside")

# Sentinel to signal threads to stop
_STOP = object()
_DONE = object()


class TTSPipeline:
    """Kokoro TTS synthesis and audio playback pipeline."""

    def __init__(self, model="af_heart", speed=1.0, lang="a"):
        self._model_name = model
        self._speed = speed
        self._lang = lang
        self._pipeline = None  # Lazy-loaded KPipeline
        self._sentence_q: queue.Queue = queue.Queue()
        self._audio_q: queue.Queue = queue.Queue()
        self._synth_thread: threading.Thread | None = None
        self._play_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        """Lazy-load the Kokoro model on first use."""
        if self._pipeline is not None:
            return
        log.info("Loading Kokoro TTS model (voice=%s, lang=%s)...", self._model_name, self._lang)
        try:
            from kokoro import KPipeline
            self._pipeline = KPipeline(lang_code=self._lang)
            log.info("Kokoro TTS loaded successfully")
        except Exception:
            log.exception("Failed to load Kokoro TTS")
            raise

    def update_config(self, model: str, speed: float, lang: str):
        """Update voice settings. Takes effect on next sentence."""
        self._model_name = model
        self._speed = speed
        if lang != self._lang:
            self._lang = lang
            self._pipeline = None  # Force reload for new language

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
        """Thread: pull sentences, synthesize with Kokoro, push audio."""
        try:
            self._ensure_loaded()
        except Exception:
            self._audio_q.put(_STOP)
            return

        while True:
            item = self._sentence_q.get()
            if item is _STOP:
                self._audio_q.put(_STOP)
                break
            if item is _DONE:
                self._audio_q.put(_DONE)
                break
            try:
                # Kokoro returns a generator; we take the first segment
                for _gs, _ps, audio in self._pipeline(
                    item, voice=self._model_name, speed=self._speed
                ):
                    if not self._running:
                        break
                    self._audio_q.put(audio)
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
                sd.play(item, samplerate=24000, device=pw_dev)
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
