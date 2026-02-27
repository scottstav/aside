"""Audio capture pipeline with pre-roll buffer and VAD.

Provides a two-phase audio pipeline for voice input:
1. Wake word detection phase: read 80ms chunks for OpenWakeWord while
   keeping a rolling pre-roll buffer of 30ms frames.
2. Speech capture phase: read 30ms frames with WebRTC VAD, accumulating
   audio until the caller decides speech has ended.

Uses pw-record (PipeWire) for audio capture instead of PyAudio, since
PortAudio's ALSA backend doesn't reliably route through PipeWire.
"""

import collections
import fcntl
import logging
import os
import subprocess

import numpy as np
import webrtcvad

log = logging.getLogger(__name__)

# Audio stream parameters
RATE = 16000
CHANNELS = 1
VAD_FRAME_MS = 30
VAD_FRAME_SAMPLES = int(RATE * VAD_FRAME_MS / 1000)  # 480 samples
OWW_CHUNK = 1280  # 80ms for OpenWakeWord
BYTES_PER_SAMPLE = 2  # int16


class AudioPipeline:
    """Mic capture with pre-roll buffering and WebRTC VAD.

    The pipeline operates in two modes controlled by the caller:

    **Listening mode** (default): ``read_oww_chunk()`` pulls 80ms chunks
    from the mic for wake word scoring. Each chunk is also sliced into
    30ms frames and pushed into a circular pre-roll buffer so that the
    start of the utterance is not lost.

    **Capture mode**: after a wake word fires, ``begin_capture()`` moves
    the pre-roll into a capture buffer. The caller then loops on
    ``read_vad_frame()`` which returns one 30ms frame at a time together
    with a VAD speech flag. ``end_capture()`` returns all accumulated
    audio and resets for the next cycle.
    """

    def __init__(self, pre_roll_seconds: float = 0.5, input_device: str | None = None):
        self._proc: subprocess.Popen | None = None
        self._input_device = input_device  # unused now, pw-record uses PipeWire default

        # WebRTC VAD at aggressiveness 2 (moderate filtering)
        self._vad = webrtcvad.Vad(2)

        # Pre-roll: circular buffer of raw 30ms frames (bytes)
        frames_in_pre_roll = int(pre_roll_seconds / (VAD_FRAME_MS / 1000))
        self._pre_roll: collections.deque[bytes] = collections.deque(
            maxlen=max(frames_in_pre_roll, 1)
        )

        # Capture buffer: list of raw 30ms frames (bytes)
        self._capture_buf: list[bytes] = []

    # ------------------------------------------------------------------
    # Stream lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the microphone stream via pw-record subprocess."""
        cmd = [
            "pw-record",
            "--rate", str(RATE),
            "--channels", str(CHANNELS),
            "--format", "s16",
            "--target", "@DEFAULT_SOURCE@",
            "-",  # write to stdout
        ]
        log.info("Starting pw-record: %s", " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        # pw-record outputs a 24-byte SND/AU header before raw PCM
        self._read_exact(24)

    def stop(self) -> None:
        """Kill the pw-record subprocess."""
        if self._proc is not None:
            log.info("Stopping pw-record")
            self._proc.terminate()
            self._proc.wait()
            self._proc = None

    def _read_exact(self, num_bytes: int) -> bytes:
        """Read exactly num_bytes from the pw-record stdout."""
        data = self._proc.stdout.read(num_bytes)
        if len(data) < num_bytes:
            raise IOError("pw-record stream ended unexpectedly")
        return data

    # ------------------------------------------------------------------
    # Wake word detection phase
    # ------------------------------------------------------------------

    def read_oww_chunk(self) -> np.ndarray:
        """Read an 80ms (1280-sample) chunk for OpenWakeWord.

        The chunk is also split into 30ms VAD frames and stored in the
        pre-roll buffer so that audio preceding a wake word detection is
        preserved.

        Returns:
            int16 numpy array of shape ``(1280,)``.
        """
        raw = self._read_exact(OWW_CHUNK * BYTES_PER_SAMPLE)
        samples = np.frombuffer(raw, dtype=np.int16)

        # Slice into 30ms frames for the pre-roll buffer.
        # 1280 samples / 480 = 2 full frames + 320 leftover.
        # We store only complete 30ms frames.
        offset = 0
        while offset + VAD_FRAME_SAMPLES <= len(samples):
            frame_bytes = samples[offset : offset + VAD_FRAME_SAMPLES].tobytes()
            self._pre_roll.append(frame_bytes)
            offset += VAD_FRAME_SAMPLES

        return samples

    # ------------------------------------------------------------------
    # Speech capture phase
    # ------------------------------------------------------------------

    def begin_capture(self, skip_pre_roll: bool = False) -> None:
        """Switch from listening mode to capture mode.

        Args:
            skip_pre_roll: If True, discard pre-roll audio instead of
                including it. Use for wake word triggers where the
                pre-roll contains wake word audio (e.g. "computer").
        """
        if skip_pre_roll:
            self._capture_buf = []
        else:
            self._capture_buf = list(self._pre_roll)
        self._pre_roll.clear()
        log.debug(
            "Capture started with %d pre-roll frames (%.0f ms)",
            len(self._capture_buf),
            len(self._capture_buf) * VAD_FRAME_MS,
        )

    def read_vad_frame(self) -> tuple[bytes, bool]:
        """Read a single 30ms frame and run VAD on it.

        The frame is appended to the capture buffer automatically.

        Returns:
            ``(raw_bytes, is_speech)`` where *raw_bytes* is 960 bytes of
            int16 PCM and *is_speech* is the WebRTC VAD verdict.
        """
        raw = self._read_exact(VAD_FRAME_SAMPLES * BYTES_PER_SAMPLE)
        is_speech = self._vad.is_speech(raw, RATE)
        self._capture_buf.append(raw)
        return raw, is_speech

    def get_captured_audio(self) -> np.ndarray:
        """Return all captured audio so far as a contiguous int16 array.

        Useful for interim transcription while capture is still ongoing.
        The capture buffer is *not* cleared.
        """
        if not self._capture_buf:
            return np.array([], dtype=np.int16)
        return np.frombuffer(b"".join(self._capture_buf), dtype=np.int16)

    def end_capture(self) -> np.ndarray:
        """End capture mode and return all captured audio.

        Returns:
            int16 numpy array containing every frame since
            ``begin_capture()`` was called (including pre-roll).
        """
        audio = self.get_captured_audio()
        log.debug(
            "Capture ended: %d samples (%.1f s)",
            len(audio),
            len(audio) / RATE if len(audio) else 0,
        )
        self._capture_buf.clear()
        return audio

    def flush(self) -> None:
        """Drain all buffered audio from the pw-record pipe.

        Call after capture to discard stale audio that accumulated
        while nobody was reading (during transcription, sleep, etc.).
        This ensures the wake word model only sees fresh audio.
        """
        if self._proc is None or self._proc.stdout is None:
            return
        fd = self._proc.stdout.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        drained = 0
        try:
            while True:
                try:
                    chunk = self._proc.stdout.read1(65536)
                    if not chunk:
                        break
                    drained += len(chunk)
                except BlockingIOError:
                    break
        finally:
            fcntl.fcntl(fd, fcntl.F_SETFL, flags)
        self._pre_roll.clear()
        if drained:
            log.debug("Flushed %d bytes of stale audio from pipe", drained)
