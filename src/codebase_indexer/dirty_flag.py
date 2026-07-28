"""Thread-safe repository dirty-state signal."""

from __future__ import annotations

from threading import Lock

__all__ = ["DIRTY", "DirtyFlag"]


class DirtyFlag:
    """Store a boolean signal shared by watcher and MCP request threads."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._value = False

    def set(self, value: bool = True) -> None:
        with self._lock:
            self._value = value

    def is_set(self) -> bool:
        with self._lock:
            return self._value

    def check_and_clear(self) -> bool:
        with self._lock:
            previous = self._value
            self._value = False
            return previous


DIRTY = DirtyFlag()
