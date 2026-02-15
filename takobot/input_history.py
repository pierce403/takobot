from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class InputHistory:
    max_items: int = 200
    _entries: deque[str] = field(init=False, repr=False)
    _cursor: int | None = field(default=None, init=False, repr=False)
    _draft: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_items < 1:
            msg = "max_items must be >= 1"
            raise ValueError(msg)
        self._entries = deque(maxlen=self.max_items)

    def add(self, text: str) -> None:
        if not text:
            return
        if self._entries and self._entries[-1] == text:
            self.reset_navigation()
            return
        self._entries.append(text)
        self.reset_navigation()

    def navigate_up(self, current_text: str) -> str | None:
        if not self._entries:
            return None
        if self._cursor is None:
            self._draft = current_text
            self._cursor = len(self._entries) - 1
        elif self._cursor > 0:
            self._cursor -= 1
        return self._entries[self._cursor]

    def navigate_down(self) -> str | None:
        if self._cursor is None:
            return None
        if self._cursor < len(self._entries) - 1:
            self._cursor += 1
            return self._entries[self._cursor]
        draft = self._draft
        self.reset_navigation()
        return draft

    def reset_navigation(self) -> None:
        self._cursor = None
        self._draft = ""
