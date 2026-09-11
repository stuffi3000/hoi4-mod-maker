"""CommandBus — Command bus, responsible for command execution + undo/redo stack management + change broadcast.

Usage:
    bus = CommandBus(max_history=30)
    bus.execute(PaintCommand(...))
    bus.undo()
    bus.redo()
    bus.on_change(lambda: refresh_ui())"""

from __future__ import annotations

from collections import deque
from typing import Callable

from commands.base import Command


class CommandBus:
    """Command bus. Does not depend on Qt, can be run in pure Python tests."""

    def __init__(self, max_history: int = 30) -> None:
        self._undo_stack: deque[Command] = deque(maxlen=max_history)
        self._redo_stack: list[Command] = []
        self._listeners: list[Callable[[], None]] = []

    def execute(self, cmd: Command) -> None:
        """Execute a new command to clear the redo stack."""
        cmd.execute()
        # Try to merge the same type of consecutive commands with the top of the stack (such as a brush stroke)
        if self._undo_stack and self._undo_stack[-1].can_merge_with(cmd):
            self._undo_stack[-1].merge(cmd)
        else:
            self._undo_stack.append(cmd)
        self._redo_stack.clear()
        self._emit_change()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        cmd = self._undo_stack.pop()
        cmd.undo()
        self._redo_stack.append(cmd)
        self._emit_change()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        cmd = self._redo_stack.pop()
        cmd.execute()
        self._undo_stack.append(cmd)
        self._emit_change()
        return True

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._emit_change()

    def on_change(self, listener: Callable[[], None]) -> None:
        """Register change callback (triggered when command execution/undo/redo)."""
        self._listeners.append(listener)

    def _emit_change(self) -> None:
        for fn in self._listeners:
            try:
                fn()
            except Exception:
                # A single listener crash should not affect command execution
                pass

    # Debugging/Testing Assistance
    def history_labels(self) -> list[str]:
        return [c.label for c in self._undo_stack]

    def undo_depth(self) -> int:
        return len(self._undo_stack)

    def redo_depth(self) -> int:
        return len(self._redo_stack)
