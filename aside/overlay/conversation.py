"""Scrollable message history widget for the aside overlay."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from aside.overlay.message_view import MessageView  # noqa: E402

log = logging.getLogger(__name__)


class ConversationHistory(Gtk.ScrolledWindow):
    """Scrollable container holding an ordered list of MessageView widgets."""

    def __init__(self, markdown: bool = True) -> None:
        super().__init__()
        self._markdown = markdown
        self._messages: list[MessageView] = []
        self._auto_scroll = True

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._box.set_margin_bottom(16)
        self.set_child(self._box)

        self.set_hexpand(True)
        self.set_vexpand(True)

    def _scroll_to_end(self) -> None:
        """Scroll to make the last message visible."""
        if not self._messages:
            return
        last = self._messages[-1]
        # GTK 4.12+ scroll_to: scrolls viewport to make child visible.
        try:
            self.scroll_to(last, Gtk.ScrolledWindowScrollFlags.NONE, None)
        except (TypeError, AttributeError):
            # Fallback for older GTK4: use vadjustment
            vadj = self.get_vadjustment()
            if vadj:
                vadj.set_value(vadj.get_upper() - vadj.get_page_size())

    def scroll_to_bottom(self) -> None:
        """Explicitly request scroll-to-bottom."""
        self._scroll_to_end()

    def content_height(self) -> float:
        """Return the actual content height (vadjustment upper)."""
        vadj = self.get_vadjustment()
        return vadj.get_upper() if vadj else 0

    def add_message(self, role: str, text: str) -> MessageView:
        mv = MessageView(role=role, text="", markdown=self._markdown)
        self._messages.append(mv)
        self._box.append(mv)
        if text:
            GLib.idle_add(self._deferred_set_text, mv, text)
        return mv

    def _deferred_set_text(self, mv: MessageView, text: str) -> bool:
        mv.set_text(text)
        self._scroll_to_end()
        return False

    def _apply_pending_text(self, pending: list) -> bool:
        """Set text on MessageViews after they're realized in the tree."""
        for mv, text in pending:
            if text:
                mv.set_text(text)
        self._scroll_to_end()
        # Retry after layout settles
        GLib.timeout_add(100, self._delayed_scroll)
        GLib.timeout_add(500, self._delayed_scroll)
        return False

    def _delayed_scroll(self) -> bool:
        self._scroll_to_end()
        return False

    def update_last_message(self, text: str) -> None:
        if self._messages:
            self._messages[-1].set_text(text)
            self._scroll_to_end()

    def get_last_message(self) -> MessageView | None:
        return self._messages[-1] if self._messages else None

    def message_count(self) -> int:
        return len(self._messages)

    def clear(self) -> None:
        for mv in self._messages:
            self._box.remove(mv)
        self._messages.clear()

    def load_conversation(self, conv: dict) -> None:
        """Clear and populate from a conversation dict.

        Text is applied in a deferred callback so TextViews have valid
        PangoContexts before measuring with text.
        """
        self.clear()
        pending: list[tuple[MessageView, str]] = []
        for msg in conv.get("messages", []):
            role = msg.get("role", "")
            if role == "tool":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                text = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            else:
                text = str(content)
            mv = self.add_message(role, "")
            pending.append((mv, text))
        GLib.idle_add(self._apply_pending_text, pending)
