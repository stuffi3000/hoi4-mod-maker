"""SetStatePropertyCommand — Modify any property of State."""

from __future__ import annotations

from typing import Any

from commands.base import Command


class SetStatePropertyCommand(Command):
    """Modify a property value of State."""

    label = "Change state property"

    def __init__(
        self,
        state_mgr,
        state_id: int,
        prop_name: str,
        old_value: Any,
        new_value: Any,
    ) -> None:
        """Parameters:
            state_mgr: StateManager instance
            state_id: State ID
            prop_name: attribute name (such as 'name', 'manpower', 'category')
            old_value: old value
            new_value: new value"""
        self._state_mgr = state_mgr
        self._state_id = state_id
        self._prop_name = prop_name
        self._old_value = old_value
        self._new_value = new_value

    def _set_value(self, value: Any) -> None:
        """Set the State property value."""
        state = self._state_mgr.get_state(self._state_id)
        if state is not None:
            setattr(state, self._prop_name, value)

    def execute(self) -> None:
        """Set new value."""
        self._set_value(self._new_value)

    def undo(self) -> None:
        """Restore old value."""
        self._set_value(self._old_value)
