"""Sentence buffer: accumulates streaming text, yields complete sentences.

Strips markdown formatting, skips code blocks and bare URLs,
and detects sentence boundaries for TTS consumption.
"""

import re

# Sentence boundary: period, question mark, or exclamation followed by
# whitespace (or end-of-string after flush).  We split on these but keep
# the punctuation attached to the sentence.
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+|(?<=\n)')

# Common abbreviations that should NOT be treated as sentence endings.
# Matched case-insensitively against the last word before the period.
_ABBREVIATIONS = frozenset({
    'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr',
    'st', 'ave', 'blvd',
    'vs', 'etc', 'approx', 'dept', 'est', 'govt', 'inc', 'ltd', 'univ',
    # Latin abbreviations (e.g., i.e. are handled by the multi-dot pattern)
    'e.g', 'i.e',
})

# Detect abbreviation ending: a known abbreviation followed by a period
_ABBREV_TAIL = re.compile(r'(?:^|\s)(\S+)\.$')

# Markdown patterns to strip
_BOLD_ITALIC = re.compile(r'\*{1,3}(.*?)\*{1,3}')
_INLINE_CODE = re.compile(r'`([^`]+)`')
_MD_IMAGE = re.compile(r'!\[.*?\]\(.*?\)')
_MD_LINK = re.compile(r'\[([^\]]+)\]\([^\)]+\)')
_BARE_URL = re.compile(r'https?://\S+')
_HEADING = re.compile(r'^#{1,6}\s+', re.MULTILINE)

# Multiple consecutive spaces collapsed to one
_MULTIPLE_SPACES = re.compile(r'  +')

# Fenced code block detection
_CODE_FENCE = re.compile(r'^```', re.MULTILINE)

# Emoji characters: emoticons, dingbats, symbols, flags, skin tones, ZWJ sequences
_EMOJI = re.compile(
    '['
    '\U0001F300-\U0001FAFF'  # Misc Symbols/Pictographs, Emoticons, Transport, etc.
    '\U00002600-\U000027BF'  # Misc Symbols, Dingbats
    '\U0000FE00-\U0000FE0F'  # Variation Selectors
    '\U0000200D'             # Zero Width Joiner
    '\U000020E3'             # Combining Enclosing Keycap
    '\U0001F1E0-\U0001F1FF'  # Regional Indicator Symbols (flags)
    ']+',
    re.UNICODE,
)

# Decorative/symbolic Unicode that TTS should not pronounce
_SYMBOLS = re.compile(
    '['
    '\u2190-\u21FF'  # Arrows (←↑→↓⇒⟹ etc.)
    '\u2500-\u257F'  # Box Drawing
    '\u2580-\u259F'  # Block Elements
    '\u25A0-\u25FF'  # Geometric Shapes (▪▸◆◇ etc.)
    '\u2700-\u27BF'  # Dingbats (✓✗✔✘ etc.)
    '\u2022'         # Bullet •
    '\u25E6'         # White bullet ◦
    '\u2605\u2606'   # Stars ★☆
    '\u00A9'         # ©
    '\u00AE'         # ®
    '\u2122'         # ™
    '\u00B0'         # °
    '\u27F9'         # ⟹
    ']+',
    re.UNICODE,
)



def _ends_with_abbreviation(text: str) -> bool:
    """Return True if *text* ends with a known abbreviation followed by a period."""
    m = _ABBREV_TAIL.search(text)
    if not m:
        return False
    word = m.group(1).lower()
    return word in _ABBREVIATIONS


class SentenceBuffer:
    """Accumulate streaming text chunks and yield complete sentences."""

    def __init__(self):
        self._buffer = ""
        self._in_code_block = False

    def add(self, text: str) -> list[str]:
        """Add a text chunk. Returns list of complete sentences (may be empty)."""
        self._buffer += text
        return self._extract_sentences()

    def flush(self) -> list[str]:
        """Return any remaining buffered text as a sentence."""
        if not self._buffer.strip():
            self._buffer = ""
            return []
        text = self._buffer.strip()
        self._buffer = ""
        text = self._clean(text)
        return [text] if text.strip() else []

    def clear(self):
        """Discard all buffered text."""
        self._buffer = ""
        self._in_code_block = False

    def _extract_sentences(self) -> list[str]:
        """Split buffer on sentence boundaries, keep remainder buffered."""
        sentences = []

        # Process code fences line by line
        lines = self._buffer.split('\n')
        clean_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if _CODE_FENCE.match(line.strip()):
                if self._in_code_block:
                    self._in_code_block = False
                else:
                    self._in_code_block = True
                i += 1
                continue
            if self._in_code_block:
                i += 1
                continue
            clean_lines.append(line)
            i += 1

        # Rejoin non-code text
        text = '\n'.join(clean_lines)

        # Split on sentence boundaries
        parts = _SENTENCE_RE.split(text)

        # Rejoin parts that were incorrectly split on abbreviation periods
        merged: list[str] = [parts[0]]
        for part in parts[1:]:
            if _ends_with_abbreviation(merged[-1]):
                merged[-1] = merged[-1] + " " + part
            else:
                merged.append(part)

        # Last part might be incomplete -- keep it buffered
        self._buffer = merged[-1]
        complete = merged[:-1]

        for part in complete:
            cleaned = self._clean(part.strip())
            if cleaned.strip():
                sentences.append(cleaned)

        return sentences

    def _clean(self, text: str) -> str:
        """Strip markdown formatting, URLs, image refs, emojis, symbols from text."""
        text = _EMOJI.sub('', text)
        text = _SYMBOLS.sub('', text)
        text = _MD_IMAGE.sub('', text)
        text = _MD_LINK.sub(r'\1', text)
        text = _BARE_URL.sub('', text)
        text = _BOLD_ITALIC.sub(r'\1', text)
        text = _INLINE_CODE.sub(r'\1', text)
        text = _HEADING.sub('', text)
        text = _MULTIPLE_SPACES.sub(' ', text)
        return text.strip()
