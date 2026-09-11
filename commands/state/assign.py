"""AssignProvinceToStateCommand — Assigns a province to the specified State."""

from __future__ import annotations

from commands.base import Command


class AssignProvinceToStateCommand(Command):
    """Move provinces from one State to another."""

    label = "Assign provinces to state"

    def __init__(
        self,
        state_mgr,
        pid: int,
        old_state_id: int,
        new_state_id: int,
    ) -> None:
        """Parameters:
            state_mgr: StateManager instance
            pid: province ID
            old_state_id: old State ID (0=not assigned)
            new_state_id: new State ID"""
        self._state_mgr = state_mgr
        self._pid = pid
        self._old_state_id = old_state_id
        self._new_state_id = new_state_id

    def execute(self) -> None:
        """Move provinces to new State."""
        self._state_mgr.assign_province(self._pid, self._new_state_id)

    def undo(self) -> None:
        """Move provinces back to old State."""
        self._state_mgr.assign_province(self._pid, self._old_state_id)
