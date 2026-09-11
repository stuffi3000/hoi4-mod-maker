"""AssignStateToCountryCommand — Assigns a State to a country."""

from __future__ import annotations

from commands.base import Command


class AssignStateToCountryCommand(Command):
    """Transfer ownership of a State from one country to another."""

    label = "Assign state to country"

    def __init__(
        self,
        country_mgr,
        state_id: int,
        old_tag: str,
        new_tag: str,
    ) -> None:
        """Parameters:
            country_mgr: CountryManager instance
            state_id: State ID
            old_tag: original country TAG (empty string = not assigned)
            new_tag: new country TAG (empty string = deallocated)"""
        self._country_mgr = country_mgr
        self._state_id = state_id
        self._old_tag = old_tag
        self._new_tag = new_tag

    def execute(self) -> None:
        """Assign State to the new country."""
        self._country_mgr.assign_state(self._state_id, self._new_tag)

    def undo(self) -> None:
        """Restore State to the old state."""
        self._country_mgr.assign_state(self._state_id, self._old_tag)
