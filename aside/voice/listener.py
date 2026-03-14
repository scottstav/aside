"""One-shot voice capture -- record until silence, then transcribe.

Provides ``capture_one_shot(config)`` which opens the microphone, records
until the user stops speaking (using VAD + silence detection), transcribes
via STT, and returns the text.  This is a blocking call.
"""

import logging
import math
import threading
import time

log = logging.getLogger(__name__)


def capture_one_shot(config: dict, on_interim=None, on_audio_level=None,
                     on_capture_end=None, cancel_event=None) -> str:
    """Record speech from the microphone and return the transcription.

    Opens the microphone, records audio frames with VAD-based silence
    detection, transcribes the result, and returns the text.  Returns
    an empty string if no speech is detected within the timeout.

    This is a **blocking** call -- it records, transcribes, and returns.

    Args:
        config: The ``[voice]`` section of the aside config dict.
                Expected keys: ``stt_model``, ``stt_device``,
                ``smart_silence``, ``silence_timeout``,
                ``no_speech_timeout``, ``force_send_phrases``, and
                optionally ``max_capture_seconds``.
        on_interim: Optional callback ``(text: str) -> None`` called with
                    each interim transcription (~every 2s).
        cancel_event: Optional ``threading.Event`` — when set, capture
                      stops immediately and returns empty string.

    Returns:
        Transcribed text string, or empty string if no speech detected.
    """
    # Lazy imports -- avoid loading heavy deps at module level
    from .audio import RATE, VAD_FRAME_MS, AudioPipeline
    from .speech_detector import SpeechEndDetector
    from .stt import transcribe

    whisper_config = {
        "model": config.get("stt_model", "base"),
        "device": config.get("stt_device", "cpu"),
    }

    audio = AudioPipeline()
    detector = SpeechEndDetector(
        silence_timeout=config.get("silence_timeout", 2.5),
        smart_silence=config.get("smart_silence", True),
        force_send_phrases=config.get("force_send_phrases", []),
    )

    audio.start()
    try:
        return _do_capture(audio, detector, whisper_config, config, on_interim,
                           on_audio_level, on_capture_end, cancel_event)
    finally:
        audio.stop()


def _do_capture(audio, detector, whisper_config: dict, config: dict,
                on_interim=None, on_audio_level=None, on_capture_end=None,
                cancel_event=None) -> str:
    """Core capture loop: read frames, detect silence, transcribe.

    Separated from ``capture_one_shot`` so that audio.stop() is always
    called in the finally block of the caller.
    """
    from .audio import RATE, VAD_FRAME_MS
    from .speech_detector import SpeechEndDetector
    from .stt import transcribe

    audio.begin_capture()
    detector.on_speech_start()
    log.debug("capture: loop starting")

    silence_frames = 0
    consecutive_speech = 0
    last_interim_time = 0
    last_level_time = 0
    last_debug_time = 0
    capture_start = time.monotonic()
    heard_speech = False
    no_speech_timeout = config.get("no_speech_timeout", 3.0)
    max_capture_seconds = config.get("max_capture_seconds", 60)
    last_transcript = ""
    transcript_stall_count = 0
    # Background transcription state
    _transcribing = False
    _transcribe_lock = threading.Lock()
    _force_break = False
    _transcribe_done_count = 0  # how many transcriptions have completed

    def _do_interim_transcribe(audio_data):
        """Run interim transcription in background thread."""
        nonlocal heard_speech, last_transcript, transcript_stall_count
        nonlocal _transcribing, _force_break, _transcribe_done_count
        try:
            t0 = time.monotonic()
            log.debug("capture: interim transcribe start (%.1f bytes)", len(audio_data))
            interim_text = transcribe(audio_data, whisper_config)
            log.debug("capture: interim transcribe done in %.2fs: %r",
                       time.monotonic() - t0, interim_text.strip()[:80])
            detector.update_transcript(interim_text)
            if interim_text.strip():
                heard_speech = True
                if on_interim:
                    try:
                        on_interim(interim_text.strip())
                    except Exception:
                        pass

            # Transcript stall detection
            if heard_speech and interim_text.strip() == last_transcript:
                transcript_stall_count += 1
                if transcript_stall_count >= 3:
                    log.info(
                        "Transcript unchanged for %d iterations, ending capture",
                        transcript_stall_count,
                    )
                    _force_break = True
            else:
                transcript_stall_count = 0
            last_transcript = interim_text.strip()
        except Exception:
            log.exception("Interim transcription error")
        finally:
            with _transcribe_lock:
                _transcribing = False
                _transcribe_done_count += 1
            log.debug("capture: interim done, _transcribing=False, done_count=%d", _transcribe_done_count)

    try:
        while True:
            if _force_break:
                break

            if cancel_event is not None and cancel_event.is_set():
                log.info("Mic capture cancelled")
                audio.end_capture()
                return ""

            raw, is_speech = audio.read_vad_frame()
            detector.on_voice_activity(is_speech)

            # Send audio level for waveform visualization (~10 Hz)
            if on_audio_level is not None:
                now_level = time.monotonic()
                if now_level - last_level_time >= 0.1:
                    last_level_time = now_level
                    import struct
                    samples = struct.unpack(f"<{len(raw)//2}h", raw)
                    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                    level = min(1.0, rms / 8000.0)  # normalize to 0-1
                    try:
                        on_audio_level(level)
                    except Exception:
                        pass

            # Debounced speech detection: require 2+ consecutive speech
            # frames to reset silence counter.
            if is_speech:
                consecutive_speech += 1
                if consecutive_speech >= 2:
                    silence_frames = 0
                    heard_speech = True
            else:
                consecutive_speech = 0
                silence_frames += 1

            # Periodic debug status (~every 1s)
            now = time.monotonic()
            if now - last_debug_time >= 1.0:
                last_debug_time = now
                elapsed = now - capture_start
                silence_sec = silence_frames * (VAD_FRAME_MS / 1000)
                log.debug(
                    "capture: t=%.1fs heard=%s vad=%s silence=%.1fs "
                    "transcribing=%s done_count=%d",
                    elapsed, heard_speech, is_speech, silence_sec,
                    _transcribing, _transcribe_done_count,
                )

            # Interim transcription every ~2 seconds (non-blocking)
            if now - last_interim_time >= 2.0:
                last_interim_time = now

                # Bail if no words detected after timeout (only after
                # at least one transcription has actually completed)
                if (not heard_speech
                        and _transcribe_done_count > 0
                        and (now - capture_start) >= no_speech_timeout):
                    log.info(
                        "No speech detected after %.1fs, discarding",
                        now - capture_start,
                    )
                    audio.end_capture()
                    return ""

                # Check for force-send phrase
                phrase = detector.check_force_send()
                if phrase:
                    log.info("Force-send phrase detected: %r", phrase)
                    final_audio = audio.end_capture()
                    final_text = transcribe(final_audio, whisper_config)
                    final_text = SpeechEndDetector.strip_force_phrase(final_text, phrase)
                    return final_text.strip()

                # Only start transcription if previous one finished
                with _transcribe_lock:
                    if not _transcribing:
                        full_audio = audio.get_captured_audio()
                        if len(full_audio) > 0:
                            log.debug("capture: launching interim transcribe (%d samples)", len(full_audio))
                            _transcribing = True
                            threading.Thread(
                                target=_do_interim_transcribe,
                                args=(full_audio,),
                                daemon=True,
                            ).start()
                    else:
                        log.debug("capture: skipping interim (previous still running)")

            # Hard limit on capture duration
            if (now - capture_start) >= max_capture_seconds:
                log.info("Max capture duration reached (%.0fs)", max_capture_seconds)
                break

            # Check silence timeout (using audio time, not wall-clock)
            silence_seconds = silence_frames * (VAD_FRAME_MS / 1000)
            if silence_seconds > 0 and detector.is_done(silence_seconds):
                log.info("Silence timeout reached (%.1fs audio time)", silence_seconds)
                break

    except Exception:
        log.exception("Error during speech capture")
        audio.end_capture()
        return ""

    # Final transcription
    log.debug("capture: loop ended, calling end_capture")
    final_audio = audio.end_capture()
    log.debug("capture: got %d samples (%.2fs)", len(final_audio), len(final_audio) / RATE)
    if len(final_audio) < RATE * 0.3:  # < 0.3s = probably false trigger
        log.info("Audio too short (%.2fs), discarding", len(final_audio) / RATE)
        return ""

    # Signal that capture is done (overlay can transition before slow transcription)
    if on_capture_end:
        log.debug("capture: calling on_capture_end callback")
        try:
            on_capture_end()
        except Exception:
            pass

    log.debug("capture: starting final transcription")
    t0 = time.monotonic()
    final_text = transcribe(final_audio, whisper_config)
    log.debug("capture: final transcription done in %.2fs: %r",
              time.monotonic() - t0, final_text.strip()[:80] if final_text else "")
    if final_text.strip():
        return final_text.strip()

    log.info("Empty transcription, discarding")
    return ""
