"""Speech-to-text module wrapping faster-whisper.

Provides a lazy-loaded Whisper model singleton and a ``transcribe()``
function the daemon calls for both interim and final transcription.
"""

import logging

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

# Module-level model cache -- loaded once, reused across calls.
_model: WhisperModel | None = None
_model_config: tuple[str, str] | None = None


def _get_model(whisper_config: dict) -> WhisperModel:
    """Return a cached WhisperModel, reloading only when config changes.

    Args:
        whisper_config: Dict with ``model`` (e.g. "base", "small") and
                        ``device`` (``"cpu"`` or ``"cuda"``).

    Returns:
        A ready-to-use ``WhisperModel`` instance.
    """
    global _model, _model_config

    model_name = whisper_config["model"]
    device = whisper_config["device"]
    key = (model_name, device)

    if _model is not None and _model_config == key:
        return _model

    compute_type = "float16" if device == "cuda" else "int8"
    log.info(
        "Loading Whisper model: %s (device=%s, compute_type=%s)",
        model_name,
        device,
        compute_type,
    )
    _model = WhisperModel(model_name, device=device, compute_type=compute_type)
    _model_config = key
    log.info("Whisper model loaded")
    return _model


def transcribe(audio: np.ndarray, whisper_config: dict) -> str:
    """Transcribe a 16 kHz int16 audio buffer to text.

    Args:
        audio:          Numpy int16 array of 16 kHz mono audio samples.
        whisper_config: Dict with ``model`` and ``device`` keys, passed
                        through to :func:`_get_model`.

    Returns:
        Transcribed text (stripped), or an empty string if the audio is
        empty or contains no speech.
    """
    if len(audio) == 0:
        return ""

    model = _get_model(whisper_config)

    # faster-whisper expects float32 in [-1, 1].
    audio_float = audio.astype(np.float32) / 32768.0

    segments, _ = model.transcribe(
        audio_float,
        beam_size=5,
        language="en",
        vad_filter=True,
    )

    text = " ".join(seg.text for seg in segments).strip()
    log.info("Transcription result: %r", text)
    return text
