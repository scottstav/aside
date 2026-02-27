"""End-of-speech detection module.

Determines when the user is done speaking using a hybrid approach:
silence duration thresholds (optionally adjusted by transcript content)
and force-send phrase detection.
"""

import re


# Words that suggest the speaker is mid-sentence and likely to continue.
# Includes prepositions, conjunctions, articles, and common "expecting object" verbs.
_MID_SENTENCE_WORDS = frozenset({
    # prepositions
    "in", "on", "at", "to", "for", "with", "from", "by", "about",
    "of", "into", "through", "during", "before", "after", "between",
    "under", "over", "above", "below",
    # conjunctions
    "and", "but", "or", "nor", "so", "yet", "because", "although",
    "while", "if", "when", "that", "than",
    # articles / determiners
    "the", "a", "an", "this", "that", "these", "those", "my", "your",
    "his", "her", "its", "our", "their", "some", "any", "every",
    # verbs that typically expect an object / continuation
    "search", "find", "tell", "show", "give", "make", "create",
    "write", "read", "open", "close", "run", "start", "stop",
    "get", "set", "put", "send", "list", "describe", "explain",
    "is", "are", "was", "were", "be",
})

_SENTENCE_END_RE = re.compile(r'[.?!]\s*$')


class SpeechEndDetector:
    """Detects when the user has finished speaking.

    Uses silence duration combined with optional transcript-aware
    heuristics and force-send phrase matching.
    """

    def __init__(
        self,
        silence_timeout: float = 2.5,
        smart_silence: bool = True,
        force_send_phrases: list[str] | None = None,
    ):
        self.silence_timeout = silence_timeout
        self.smart_silence = smart_silence
        self.force_send_phrases = [
            p.lower() for p in (force_send_phrases or [])
        ]
        self._transcript = ""

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def on_speech_start(self) -> None:
        """Reset state when a new speech capture session begins."""
        self._transcript = ""

    def on_voice_activity(self, is_speech: bool) -> None:
        """Called with each VAD frame result.

        Currently a hook for future use (e.g. tracking speech/silence
        frame counts). The main daemon tracks elapsed silence externally.
        """

    def update_transcript(self, text: str) -> None:
        """Update the current interim transcript."""
        self._transcript = text

    # ------------------------------------------------------------------
    # Silence-based detection
    # ------------------------------------------------------------------

    def _effective_timeout(self) -> float:
        """Return the silence timeout, adjusted for transcript if smart_silence is on."""
        if not self.smart_silence:
            return self.silence_timeout

        text = self._transcript.strip()
        if not text:
            return self.silence_timeout

        # Sentence-ending punctuation -> shorter wait
        if _SENTENCE_END_RE.search(text):
            return 1.5

        # Last word suggests mid-sentence -> longer wait
        last_word = text.split()[-1].lower().rstrip(".,;:!?")
        if last_word in _MID_SENTENCE_WORDS:
            return 3.5

        return self.silence_timeout

    def is_done(self, elapsed_silence: float) -> bool:
        """Check whether silence duration exceeds the effective timeout."""
        return elapsed_silence >= self._effective_timeout()

    # ------------------------------------------------------------------
    # Force-send detection
    # ------------------------------------------------------------------

    def check_force_send(self) -> str | None:
        """Check if the transcript ends with a force-send phrase.

        Returns the matched phrase (lowercase) or None.
        """
        text = self._transcript.strip().lower()
        if not text:
            return None

        for phrase in self.force_send_phrases:
            if text.endswith(phrase):
                # Make sure the match is either the whole text or preceded
                # by a space (so "send it" matches "weather send it" but
                # not "resend it" -- though the spec only asks about end-match).
                prefix_len = len(text) - len(phrase)
                if prefix_len == 0 or text[prefix_len - 1] == " ":
                    return phrase

        return None

    @staticmethod
    def strip_force_phrase(text: str, phrase: str) -> str:
        """Remove a force-send phrase from the end of text.

        Case-insensitive. Returns the text unchanged if the phrase
        is not at the end.
        """
        stripped = text.rstrip()
        pattern = re.compile(re.escape(phrase) + r'\s*$', re.IGNORECASE)
        result = pattern.sub('', stripped)
        return result.rstrip()
