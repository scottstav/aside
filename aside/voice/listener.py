"""One-shot voice capture -- record until silence, then transcribe.

Provides ``capture_one_shot(config)`` which opens the microphone, records
until the user stops speaking (using VAD + silence detection), transcribes
via STT, and returns the text.  This is a blocking call.

No wake-word detection, no persistent listener thread.
"""

import logging
import time

log = logging.getLogger(__name__)


def capture_one_shot(config: dict) -> str:
    """Record speech from the microphone and return the transcription.

    Opens the microphone, records audio frames with VAD-based silence
    detection, transcribes the result, and returns the text.  Returns
    an empty string if no speech is detected within the timeout.

    This is a **blocking** call -- it records, transcribes, and returns.

    Args:
        config: The ``[voice]`` section of the aside config dict.
                Expected keys: ``stt_model``, ``stt_device``,
                ``pre_roll_seconds``, ``smart_silence``, ``silence_timeout``,
                ``no_speech_timeout``, ``force_send_phrases``, and
                optionally ``max_capture_seconds``.

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

    audio = AudioPipeline(
        pre_roll_seconds=config.get("pre_roll_seconds", 0.5),
    )
    detector = SpeechEndDetector(
        silence_timeout=config.get("silence_timeout", 2.5),
        smart_silence=config.get("smart_silence", True),
        force_send_phrases=config.get("force_send_phrases", []),
    )

    audio.start()
    try:
        return _do_capture(audio, detector, whisper_config, config)
    finally:
        audio.stop()


def _do_capture(audio, detector, whisper_config: dict, config: dict) -> str:
    """Core capture loop: read frames, detect silence, transcribe.

    Separated from ``capture_one_shot`` so that audio.stop() is always
    called in the finally block of the caller.
    """
    from .audio import RATE, VAD_FRAME_MS
    from .speech_detector import SpeechEndDetector
    from .stt import transcribe

    audio.begin_capture(skip_pre_roll=False)
    detector.on_speech_start()

    silence_frames = 0
    consecutive_speech = 0
    last_interim_time = 0
    capture_start = time.monotonic()
    heard_speech = False
    no_speech_timeout = config.get("no_speech_timeout", 3.0)
    max_capture_seconds = config.get("max_capture_seconds", 60)
    last_transcript = ""
    transcript_stall_count = 0

    try:
        while True:
            raw, is_speech = audio.read_vad_frame()
            detector.on_voice_activity(is_speech)

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
                full_audio = audio.get_captured_audio()
                if len(full_audio) > 0:
                    interim_text = transcribe(full_audio, whisper_config)
                    detector.update_transcript(interim_text)
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
    final_audio = audio.end_capture()
    if len(final_audio) < RATE * 0.3:  # < 0.3s = probably false trigger
        log.info("Audio too short (%.2fs), discarding", len(final_audio) / RATE)
        return ""

    final_text = transcribe(final_audio, whisper_config)
    if final_text.strip():
        return final_text.strip()

    log.info("Empty transcription, discarding")
    return ""
