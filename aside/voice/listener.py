"""Voice listener -- wake word detection, speech capture, and STT.

Owns the audio pipeline, wake word model, and speech end detector.
Provides a ``run_wake_word_loop()`` method that the daemon calls in a
background thread.  When speech is captured and transcribed, the
provided *query_callback* is invoked.

External control is exposed via ``request_listen()``, ``set_muted()``,
and ``cancel_query()`` -- all thread-safe.
"""

import logging
import re
import subprocess
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

# Strip wake word remnants ("ok computer", "computer") from transcription start
_WAKE_WORD_RE = re.compile(r'^(ok\s+)?computer[.,!?\s:]*', re.IGNORECASE)

# Notification tag for notify-send (replaces in-place)
_NOTIFY_TAG = "aside-voice"


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

def _notify(text: str, title: str = "Aside Voice") -> None:
    """Show or update a persistent notification (replaces previous with same tag)."""
    subprocess.Popen(
        [
            "notify-send",
            "-t", "0",
            "-h", f"string:x-canonical-private-synchronous:{_NOTIFY_TAG}",
            "-a", "Aside Voice",
            title, text,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def notify_listening() -> None:
    """Show a 'Listening...' notification."""
    _notify("Listening...")


def notify_transcription(text: str | None) -> None:
    """Show live transcription text, or fall back to 'Listening...'."""
    _notify(text or "Listening...")


def notify_dismiss() -> None:
    """Dismiss the notification by replacing it with a near-instant timeout."""
    subprocess.Popen(
        [
            "notify-send",
            "-t", "1",
            "-h", f"string:x-canonical-private-synchronous:{_NOTIFY_TAG}",
            "-a", "Aside Voice",
            "Aside Voice", "",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# VoiceListener
# ---------------------------------------------------------------------------

# Type alias for the callback the daemon provides.
# Called as: query_callback(text, conversation_id)
QueryCallback = Callable[[str, str | None], None]


class VoiceListener:
    """Wake word detection loop with speech capture and STT.

    This class owns the AudioPipeline, WakeWordListener, and
    SpeechEndDetector.  It does *not* own a socket server or query
    pipeline -- those live in the daemon module.

    Args:
        config: The ``[voice]`` section of the aside config dict.
                Expected keys: ``wake_word_model``, ``wake_word_threshold``,
                ``pre_roll_seconds``, ``stt_model``, ``stt_device``,
                ``smart_silence``, ``silence_timeout``, ``no_speech_timeout``,
                ``force_send_phrases``, and optionally ``max_capture_seconds``.
    """

    def __init__(self, config: dict):
        self._config = config

        # Whisper config (used by stt.transcribe)
        self._whisper_config = {
            "model": config.get("stt_model", "base"),
            "device": config.get("stt_device", "cpu"),
        }

        # Lazily imported heavy deps -- only loaded when run_wake_word_loop
        # is actually called.  This lets tests construct VoiceListener
        # without having openwakeword / faster-whisper installed.
        self._audio = None
        self._wake_word = None
        self._detector = None

        # External listen requests (set by daemon via request_listen)
        self._listen_request: dict | None = None
        self._muted = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lazy initialisation of heavy dependencies
    # ------------------------------------------------------------------

    def _init_components(self) -> None:
        """Lazily import and initialise audio, wake word, and speech detector."""
        from .audio import AudioPipeline
        from .speech_detector import SpeechEndDetector
        from .wake_word import WakeWordListener

        cfg = self._config

        self._wake_word = WakeWordListener(
            model_path=cfg["wake_word_model"],
            threshold=cfg.get("wake_word_threshold", 0.5),
        )
        self._audio = AudioPipeline(
            pre_roll_seconds=cfg.get("pre_roll_seconds", 0.5),
        )
        self._detector = SpeechEndDetector(
            silence_timeout=cfg.get("silence_timeout", 2.5),
            smart_silence=cfg.get("smart_silence", True),
            force_send_phrases=cfg.get("force_send_phrases", []),
        )

    # ------------------------------------------------------------------
    # External control interface (thread-safe)
    # ------------------------------------------------------------------

    def request_listen(self, conversation_id: str | None = None) -> None:
        """Queue a listen request (called from the daemon's control socket)."""
        with self._lock:
            self._listen_request = {"conversation_id": conversation_id}
        log.info("Listen request queued (conv=%s)", conversation_id or "new")

    def set_muted(self, muted: bool) -> None:
        """Mute or unmute wake word detection."""
        with self._lock:
            was_muted = self._muted
            self._muted = muted
        if was_muted and not muted and self._wake_word is not None:
            self._wake_word.reset()
        log.info("Wake word %s", "muted" if muted else "unmuted")

    def _check_listen_request(self) -> dict | None:
        """Check and consume a pending listen request. Returns dict or None."""
        with self._lock:
            req = self._listen_request
            self._listen_request = None
            return req

    # ------------------------------------------------------------------
    # Post-capture cleanup
    # ------------------------------------------------------------------

    def _post_capture_reset(self) -> None:
        """Flush stale pipe audio and reset the wake word model."""
        self._audio.flush()
        self._wake_word.reset()
        log.debug("Post-capture reset: flushed audio, reset wake word model")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_wake_word_loop(self, query_callback: QueryCallback) -> None:
        """Main loop: detect wake word or external trigger, then capture speech.

        This method blocks forever (or until KeyboardInterrupt).  The
        daemon should call it in a dedicated thread.

        Args:
            query_callback: Called as ``query_callback(text, conversation_id)``
                            when speech is captured and transcribed.
        """
        from .audio import VAD_FRAME_MS, RATE

        self._init_components()
        self._audio.start()
        log.info("Wake word loop started")
        try:
            while True:
                # Check for external listen request first
                req = self._check_listen_request()
                if req is not None:
                    self._capture_and_send(
                        query_callback,
                        conversation_id=req.get("conversation_id"),
                    )
                    continue

                # Read audio and check for wake word
                chunk = self._audio.read_oww_chunk()
                if self._muted:
                    continue
                if self._wake_word.detect(chunk):
                    self._capture_and_send(
                        query_callback,
                        skip_pre_roll=True,
                    )
        except KeyboardInterrupt:
            log.info("Interrupted")
        finally:
            self._audio.stop()
            log.info("Audio pipeline stopped")

    # ------------------------------------------------------------------
    # Speech capture
    # ------------------------------------------------------------------

    def _capture_and_send(
        self,
        query_callback: QueryCallback,
        conversation_id: str | None = None,
        skip_pre_roll: bool = False,
    ) -> None:
        """Capture speech, transcribe, and invoke the query callback."""
        from .audio import VAD_FRAME_MS, RATE
        from .speech_detector import SpeechEndDetector
        from .stt import transcribe

        notify_listening()
        self._audio.begin_capture(skip_pre_roll=skip_pre_roll)
        self._detector.on_speech_start()

        # Track silence in audio time (frame count) instead of wall-clock
        # time.  Transcription blocks the frame-reading loop for ~1s, so
        # wall-clock elapsed time after a reset is near-zero when reading
        # buffered frames -- making silence detection impossible.
        silence_frames = 0
        consecutive_speech = 0  # debounce: require 2+ to reset silence
        last_interim_time = 0
        capture_start = time.monotonic()
        heard_speech = False
        no_speech_timeout = self._config.get("no_speech_timeout", 3.0)
        max_capture_seconds = self._config.get("max_capture_seconds", 60)
        last_transcript = ""
        transcript_stall_count = 0

        try:
            while True:
                raw, is_speech = self._audio.read_vad_frame()
                self._detector.on_voice_activity(is_speech)

                # Debounced speech detection: require 2+ consecutive speech
                # frames to reset silence counter.
                if is_speech:
                    consecutive_speech += 1
                    if consecutive_speech >= 2:
                        silence_frames = 0
                else:
                    consecutive_speech = 0
                    silence_frames += 1

                # Interim transcription every ~2 seconds
                now = time.monotonic()
                if now - last_interim_time >= 2.0:
                    full_audio = self._audio.get_captured_audio()
                    if len(full_audio) > 0:
                        interim_text = transcribe(full_audio, self._whisper_config)
                        self._detector.update_transcript(interim_text)
                        notify_transcription(interim_text)
                        if interim_text.strip():
                            heard_speech = True

                        # Transcript stall detection
                        if heard_speech and interim_text.strip() == last_transcript:
                            transcript_stall_count += 1
                            if transcript_stall_count >= 3:
                                log.info(
                                    "Transcript unchanged for %d iterations, ending capture",
                                    transcript_stall_count,
                                )
                                break
                        else:
                            transcript_stall_count = 0
                        last_transcript = interim_text.strip()
                    last_interim_time = now

                    # Bail if no words detected after timeout
                    if not heard_speech and (now - capture_start) >= no_speech_timeout:
                        log.info(
                            "No speech detected after %.1fs, discarding",
                            now - capture_start,
                        )
                        self._audio.end_capture()
                        self._post_capture_reset()
                        notify_dismiss()
                        return

                    # Check for force-send phrase
                    phrase = self._detector.check_force_send()
                    if phrase:
                        log.info("Force-send phrase detected: %r", phrase)
                        final_audio = self._audio.end_capture()
                        final_text = transcribe(final_audio, self._whisper_config)
                        final_text = SpeechEndDetector.strip_force_phrase(final_text, phrase)
                        if skip_pre_roll:
                            final_text = _WAKE_WORD_RE.sub('', final_text).strip()
                        if final_text.strip():
                            query_callback(final_text.strip(), conversation_id)
                        else:
                            notify_dismiss()
                        self._post_capture_reset()
                        return

                # Hard limit on capture duration
                if (now - capture_start) >= max_capture_seconds:
                    log.info("Max capture duration reached (%.0fs)", max_capture_seconds)
                    break

                # Check silence timeout (using audio time, not wall-clock)
                silence_seconds = silence_frames * (VAD_FRAME_MS / 1000)
                if silence_seconds > 0 and self._detector.is_done(silence_seconds):
                    log.info("Silence timeout reached (%.1fs audio time)", silence_seconds)
                    break

        except Exception:
            log.exception("Error during speech capture")
            self._audio.end_capture()
            self._post_capture_reset()
            notify_dismiss()
            return

        # Final transcription
        final_audio = self._audio.end_capture()
        if len(final_audio) < RATE * 0.3:  # < 0.3s = probably false trigger
            log.info("Audio too short (%.2fs), discarding", len(final_audio) / RATE)
            self._post_capture_reset()
            notify_dismiss()
            return

        final_text = transcribe(final_audio, self._whisper_config)
        # Strip wake word remnants (e.g. "computer.") from transcription
        if skip_pre_roll:
            final_text = _WAKE_WORD_RE.sub('', final_text).strip()
        if final_text.strip():
            notify_transcription(final_text.strip())
            query_callback(final_text.strip(), conversation_id)
        else:
            log.info("Empty transcription, discarding")
            notify_dismiss()
        self._post_capture_reset()
