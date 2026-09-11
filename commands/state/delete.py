"""DeleteStateCommand — delete State, supports undo (restore provinces / owner / all attributes)."""

from __future__ import annotations

import copy

from commands.base import Command


class DeleteStateCommand(Command):
    """Delete a State and clean up the owner reference pointing to it in country_mgr. Complete recovery when undoing."""

    label = "Delete state"

    def __init__(self, state_mgr, country_mgr, sid: int) -> None:
        self._state_mgr = state_mgr
        self._country_mgr = country_mgr
        self._sid = sid
        self._snapshot = None  # StateData snapshot
        self._owner_tag = ""

    def execute(self) -> None:
        state = self._state_mgr.get_state(self._sid)
        if state is None:
            return
        # Full snapshot: use copy.deepcopy because StateData contains list/dict nesting
        self._snapshot = copy.deepcopy(state)
        if self._country_mgr is not None:
            self._owner_tag = self._country_mgr.get_owner_of_state(self._sid)
            if self._owner_tag:
                self._country_mgr.assign_state(self._sid, "")
        self._state_mgr.delete_state(self._sid)

    def undo(self) -> None:
        if self._snapshot is None:
            return
        # Write back _states + rebuild inverted index
        self._state_mgr._states[self._sid] = self._snapshot
        for pid in self._snapshot.provinces:
            self._state_mgr._province_to_state[pid] = self._sid
        if self._owner_tag and self._country_mgr is not None:
            self._country_mgr.assign_state(self._sid, self._owner_tag)
