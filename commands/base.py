"""Command mode base class — encapsulates an "undoable editing action".

Each Command implements execute() and undo(). CommandBus is responsible for executing, pushing to the undo stack, and broadcasting signals.
Phase 5 will switch the snapshot undo of the old undo_manager to the imperative undo."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Command(ABC):
    """Command base class. Subclasses must implement execute() and undo()."""

    # : Human-readable description of the command, used in the UI to display "Undo: Draw Land"
    label: str = ""

    @abstractmethod
    def execute(self) -> None:
        """Execute the command. Must be reentrant (redo will be called again)."""
        ...

    @abstractmethod
    def undo(self) -> None:
        """Cancel the command. The state must be restored to before execute."""
        ...

    def can_merge_with(self, other: "Command") -> bool:
        """Whether adjacent commands of the same type (such as consecutive brush strokes) can be combined."""
        return False

    def merge(self, other: "Command") -> None:
        """Merge other into self, only called if can_merge_with returns True."""
        raise NotImplementedError
