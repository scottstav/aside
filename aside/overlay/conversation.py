"""Scrollable message history widget for the aside overlay."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from aside.overlay.message_view import MessageView  # noqa: E402


class ConversationHistory(Gtk.ScrolledWindow):
    """Scrollable container holding an ordered list of MessageView widgets."""

    def __init__(self, markdown: bool = True) -> None:
        super().__init__()
        self._markdown = markdown
        self._messages: list[MessageView] = []
        self._want_scroll = False

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_child(self._box)

        # Size to content, don't grab extra space
        self.set_hexpand(True)
        self.set_propagate_natural_height(True)

        # Scroll to bottom when layout changes (vadjustment upper updates)
        vadj = self.get_vadjustment()
        if vadj is not None:
            vadj.connect("changed", self._on_vadj_changed)

    def _on_vadj_changed(self, vadj) -> None:
        if self._want_scroll:
            vadj.set_value(vadj.get_upper())

    def add_message(self, role: str, text: str) -> MessageView:
        """Create a MessageView, append it, and scroll to bottom."""
        mv = MessageView(role=role, text=text, markdown=self._markdown)
        self._messages.append(mv)
        self._box.append(mv)
        self._want_scroll = True
        return mv

    def update_last_message(self, text: str) -> None:
        """Update the last message's text (used during streaming)."""
        if self._messages:
            self._messages[-1].set_text(text)
            self._want_scroll = True

    def get_last_message(self) -> MessageView | None:
        """Return the last message, or None if empty."""
        return self._messages[-1] if self._messages else None

    def message_count(self) -> int:
        """Return the number of messages."""
        return len(self._messages)

    def clear(self) -> None:
        """Remove all messages."""
        for mv in self._messages:
            self._box.remove(mv)
        self._messages.clear()
        self._want_scroll = False

    def load_conversation(self, conv: dict) -> None:
        """Clear and populate from a conversation dict.

        Skips tool-role messages. Handles both plain string content
        and multimodal list format (list of {type, text} dicts).
        """
        self.clear()
        for msg in conv.get("messages", []):
            role = msg.get("role", "")
            if role == "tool":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multimodal: extract text parts
                text = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            else:
                text = str(content)
            self.add_message(role, text)
