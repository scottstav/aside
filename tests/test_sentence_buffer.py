"""Tests for the sentence buffer."""

from aside.sentence_buffer import SentenceBuffer


def test_basic_sentence_detection():
    buf = SentenceBuffer()
    sentences = buf.add("Hello world. How are you? ")
    assert sentences == ["Hello world.", "How are you?"]


def test_partial_sentence_buffered():
    buf = SentenceBuffer()
    assert buf.add("Hello wor") == []
    assert buf.add("ld. ") == ["Hello world."]


def test_newline_is_boundary():
    buf = SentenceBuffer()
    sentences = buf.add("First line.\nSecond line.\n")
    assert sentences == ["First line.", "Second line."]


def test_flush_returns_remainder():
    buf = SentenceBuffer()
    buf.add("Incomplete sentence")
    assert buf.flush() == ["Incomplete sentence"]
    assert buf.flush() == []


def test_code_block_skipped():
    buf = SentenceBuffer()
    sentences = buf.add("Here is code:\n```python\nprint('hello')\n```\nDone.\n")
    # "Here is code:" spoken, code block skipped, "Done." spoken
    assert "Here is code:" in sentences
    assert "Done." in sentences
    assert not any("print" in s for s in sentences)


def test_markdown_stripped():
    buf = SentenceBuffer()
    sentences = buf.add("This is **bold** and *italic*. ")
    assert sentences == ["This is bold and italic."]


def test_url_skipped():
    buf = SentenceBuffer()
    sentences = buf.add("Check https://example.com for details. ")
    assert sentences == ["Check for details."]


def test_link_text_kept():
    buf = SentenceBuffer()
    sentences = buf.add("See [this article](https://example.com) for more. ")
    assert sentences == ["See this article for more."]


def test_image_reference_skipped():
    buf = SentenceBuffer()
    sentences = buf.add("Here: ![screenshot](image.png). And more. ")
    assert sentences == ["Here: .", "And more."]


def test_exclamation_boundary():
    buf = SentenceBuffer()
    sentences = buf.add("Wow! That's great. ")
    assert sentences == ["Wow!", "That's great."]


def test_empty_input():
    buf = SentenceBuffer()
    assert buf.add("") == []


def test_clear_resets():
    buf = SentenceBuffer()
    buf.add("Partial text")
    buf.clear()
    assert buf.flush() == []


def test_abbreviation_not_split():
    buf = SentenceBuffer()
    sentences = buf.add("Dr. Smith is here. He is great. ")
    assert sentences == ["Dr. Smith is here.", "He is great."]


def test_multiple_abbreviations():
    buf = SentenceBuffer()
    sentences = buf.add("Mr. and Mrs. Smith went to St. Louis. ")
    assert sentences == ["Mr. and Mrs. Smith went to St. Louis."]


def test_eg_abbreviation():
    buf = SentenceBuffer()
    sentences = buf.add("Use tools e.g. shell and web. ")
    assert sentences == ["Use tools e.g. shell and web."]
