"""Audio capture pipeline with VAD.

Uses pw-record (PipeWire) for audio capture instead of PyAudio, since
PortAudio's ALSA backend doesn't reliably route through PipeWire.
"""

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
BYTES_PER_SAMPLE = 2  # int16


class AudioPipeline:
    """Mic capture with WebRTC VAD.

    Call ``start()`` to open the mic, ``begin_capture()`` to start
    accumulating frames, then loop on ``read_vad_frame()`` which returns
    one 30ms frame at a time together with a VAD speech flag.
    ``end_capture()`` returns all accumulated audio and resets.
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None

        # WebRTC VAD at aggressiveness 2 (moderate filtering)
        self._vad = webrtcvad.Vad(2)

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
    # Speech capture
    # ------------------------------------------------------------------

    def begin_capture(self) -> None:
        """Start accumulating audio frames."""
        self._capture_buf = []
        log.debug("Capture started")

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
            ``begin_capture()`` was called.
        """
        audio = self.get_captured_audio()
        log.debug(
            "Capture ended: %d samples (%.1f s)",
            len(audio),
            len(audio) / RATE if len(audio) else 0,
        )
        self._capture_buf.clear()
        return audio
