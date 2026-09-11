"""DeleteCountryCommand — delete country, supports undo (restore country data + all state owners)."""

from __future__ import annotations

import copy

from commands.base import Command


class DeleteCountryCommand(Command):
    """Delete a country. Also clean up all state owners pointing to it. Complete recovery on undo."""

    label = "Delete country"

    def __init__(self, country_mgr, tag: str) -> None:
        self._country_mgr = country_mgr
        self._tag = tag.upper()[:3]
        self._snapshot = None  # CountryData Snapshot
        self._owned_state_ids: list[int] = []

    def execute(self) -> None:
        c = self._country_mgr.countries.get(self._tag)
        if c is None:
            return
        self._snapshot = copy.deepcopy(c)
        # Record all states owned by the country and redistribute them when undo
        self._owned_state_ids = [
            sid for sid, t in self._country_mgr._state_owner.items() if t == self._tag
        ]
        # remove_country will clean up _state_owner internally
        self._country_mgr.remove_country(self._tag)

    def undo(self) -> None:
        if self._snapshot is None:
            return
        self._country_mgr._countries[self._tag] = self._snapshot
        for sid in self._owned_state_ids:
            self._country_mgr._state_owner[sid] = self._tag
