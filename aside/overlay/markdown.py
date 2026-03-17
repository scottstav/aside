"""Markdown to GTK TextBuffer+TextTags renderer using mistune AST."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk, Pango

import mistune

_md = mistune.create_markdown(renderer="ast")

_FALLBACK_CODE_BG = "#2a2a2a"


def _get_code_bg() -> str:
    """Resolve @define-color code_bg from the active CSS, with fallback."""
    display = Gdk.Display.get_default()
    if display is None:
        return _FALLBACK_CODE_BG
    # Create a temporary widget to access the style context
    w = Gtk.Label()
    ctx = w.get_style_context()
    found, color = ctx.lookup_color("code_bg")
    if found:
        r = int(color.red * 255)
        g = int(color.green * 255)
        b = int(color.blue * 255)
        return f"#{r:02x}{g:02x}{b:02x}"
    return _FALLBACK_CODE_BG


def _ensure_tags(buf: Gtk.TextBuffer) -> None:
    """Create all markdown tags in the buffer's tag table if not present."""
    table = buf.get_tag_table()

    if table.lookup("bold") is None:
        buf.create_tag("bold", weight=Pango.Weight.BOLD)

    if table.lookup("italic") is None:
        buf.create_tag("italic", style=Pango.Style.ITALIC)

    code_bg = _get_code_bg()

    if table.lookup("code") is None:
        buf.create_tag("code", family="monospace", background=code_bg)

    if table.lookup("code-block") is None:
        buf.create_tag(
            "code-block",
            family="monospace",
            background=code_bg,
            paragraph_background=code_bg,
        )

    if table.lookup("h1") is None:
        buf.create_tag("h1", weight=Pango.Weight.BOLD, scale=1.6)

    if table.lookup("h2") is None:
        buf.create_tag("h2", weight=Pango.Weight.BOLD, scale=1.3)

    if table.lookup("h3") is None:
        buf.create_tag("h3", weight=Pango.Weight.BOLD, scale=1.1)

    if table.lookup("list-item") is None:
        buf.create_tag("list-item", left_margin=24)


def _insert_node(buf: Gtk.TextBuffer, node: dict, tags: list[str]) -> None:
    """Recursively walk an AST node and insert text with appropriate tags."""
    ntype = node.get("type", "")

    if ntype == "text":
        _insert_text(buf, node.get("raw", ""), tags)

    elif ntype == "paragraph":
        # Add newline before paragraph if buffer isn't empty
        end = buf.get_end_iter()
        if end.get_offset() > 0:
            buf.insert(end, "\n")
        for child in node.get("children", []):
            _insert_node(buf, child, tags)

    elif ntype == "strong":
        for child in node.get("children", []):
            _insert_node(buf, child, tags + ["bold"])

    elif ntype == "emphasis":
        for child in node.get("children", []):
            _insert_node(buf, child, tags + ["italic"])

    elif ntype == "codespan":
        _insert_text(buf, node.get("raw", ""), tags + ["code"])

    elif ntype == "block_code":
        end = buf.get_end_iter()
        if end.get_offset() > 0:
            buf.insert(end, "\n")
        raw = node.get("raw", "")
        # Strip trailing newline from block code
        if raw.endswith("\n"):
            raw = raw[:-1]
        _insert_text(buf, raw, tags + ["code-block"])

    elif ntype == "heading":
        level = node.get("attrs", {}).get("level", 1)
        tag_name = f"h{min(level, 3)}"
        end = buf.get_end_iter()
        if end.get_offset() > 0:
            buf.insert(end, "\n")
        for child in node.get("children", []):
            _insert_node(buf, child, tags + [tag_name])

    elif ntype == "list":
        for child in node.get("children", []):
            _insert_node(buf, child, tags)

    elif ntype == "list_item":
        end = buf.get_end_iter()
        if end.get_offset() > 0:
            buf.insert(end, "\n")
        _insert_text(buf, "  \u2022 ", tags)
        for child in node.get("children", []):
            _insert_node(buf, child, tags + ["list-item"])

    elif ntype == "block_text":
        # Thin wrapper inside list items — just recurse
        for child in node.get("children", []):
            _insert_node(buf, child, tags)

    elif ntype == "softbreak":
        _insert_text(buf, "\n", tags)

    elif ntype == "linebreak":
        _insert_text(buf, "\n", tags)

    elif ntype == "link":
        # Render link text only (no href display)
        for child in node.get("children", []):
            _insert_node(buf, child, tags)

    else:
        # Fallback: recurse into children or emit raw
        children = node.get("children")
        if children:
            for child in children:
                _insert_node(buf, child, tags)
        elif "raw" in node:
            _insert_text(buf, node["raw"], tags)


def _insert_text(buf: Gtk.TextBuffer, text: str, tags: list[str]) -> None:
    """Insert text at the end of the buffer with the given tag names applied."""
    if not text:
        return
    end = buf.get_end_iter()
    if tags:
        start_offset = end.get_offset()
        buf.insert(end, text)
        start = buf.get_iter_at_offset(start_offset)
        end = buf.get_end_iter()
        for tag_name in tags:
            tag = buf.get_tag_table().lookup(tag_name)
            if tag is not None:
                buf.apply_tag(tag, start, end)
    else:
        buf.insert(end, text)


def render_to_buffer(
    buf: Gtk.TextBuffer, text: str, *, enabled: bool = True
) -> None:
    """Render markdown text into a GTK TextBuffer with formatting tags.

    When enabled=False, inserts the raw text with no parsing.
    Designed for full re-parse on each call (streaming use case).
    """
    buf.set_text("", -1)  # Clear buffer

    if not enabled:
        buf.set_text(text, -1)
        return

    _ensure_tags(buf)
    ast = _md(text)

    for node in ast:
        _insert_node(buf, node, [])
