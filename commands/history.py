"""CommandHistory — Incremental undo/redo stack.

Replaces the old UndoManager (snapshot) and CommandBus.
Each Command only records what has been changed (delta) and does not save the entire map."""
from __future__ import annotations

from typing import TYPE_CHECKING

from commands.base import Command

if TYPE_CHECKING:
    from model.events import EventBus


class CommandHistory:
    """Command history stack, supports undo/redo."""

    def __init__(self, event_bus: "EventBus | None" = None, max_size: int = 200) -> None:
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._max_size = max_size
        self._event_bus = event_bus

    def execute(self, cmd: Command) -> None:
        """Execute the command and push it onto the undo stack."""
        cmd.execute()

        # Try to merge with last command (for continuous brush strokes)
        if (
            self._undo_stack
            and hasattr(cmd, "can_merge_with")
            and cmd.can_merge_with(self._undo_stack[-1])
        ):
            merged = self._undo_stack[-1]
            merged.merge(cmd)
        else:
            self._undo_stack.append(cmd)

        # Clear redo stack (new action invalidates redo history)
        self._redo_stack.clear()

        # Enforce max size
        while len(self._undo_stack) > self._max_size:
            self._undo_stack.pop(0)

        self._notify()

    def undo(self) -> bool:
        """Undo the last command. Return whether successful."""
        if not self._undo_stack:
            return False
        cmd = self._undo_stack.pop()
        cmd.undo()
        self._redo_stack.append(cmd)
        self._notify()
        return True

    def redo(self) -> bool:
        """redo. Return whether successful."""
        if not self._redo_stack:
            return False
        cmd = self._redo_stack.pop()
        cmd.execute()
        self._undo_stack.append(cmd)
        self._notify()
        return True

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def clear(self) -> None:
        """Clear all history."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._notify()

    def _notify(self) -> None:
        """Notify the UI of undo/redo status changes."""
        if self._event_bus:
            self._event_bus.emit(
                "undo_state_changed",
                can_undo=self.can_undo,
                can_redo=self.can_redo,
            )
