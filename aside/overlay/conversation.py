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

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._box.set_margin_bottom(16)
        self.set_child(self._box)

        self.set_hexpand(True)
        self.set_vexpand(True)

        # Auto-scroll to bottom on content changes
        vadj = self.get_vadjustment()
        if vadj is not None:
            vadj.connect("changed", self._on_vadj_changed)

    def _on_vadj_changed(self, vadj) -> None:
        vadj.set_value(vadj.get_upper() - vadj.get_page_size())

    def content_height(self) -> float:
        """Return the actual content height (vadjustment upper)."""
        vadj = self.get_vadjustment()
        return vadj.get_upper() if vadj else 0

    def add_message(self, role: str, text: str) -> MessageView:
        mv = MessageView(role=role, text=text, markdown=self._markdown)
        self._messages.append(mv)
        self._box.append(mv)
        return mv

    def update_last_message(self, text: str) -> None:
        if self._messages:
            self._messages[-1].set_text(text)

    def get_last_message(self) -> MessageView | None:
        return self._messages[-1] if self._messages else None

    def message_count(self) -> int:
        return len(self._messages)

    def clear(self) -> None:
        for mv in self._messages:
            self._box.remove(mv)
        self._messages.clear()

    def load_conversation(self, conv: dict) -> None:
        """Clear and populate from a conversation dict."""
        self.clear()
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
            self.add_message(role, text)
