"""QuickInitCommand — undo/redo for one-click initialization (automatically generate state/strategic_region/country).

Use deepcopy to take a snapshot of the key internal states of the three managers and restore the entire state when undoing."""

from __future__ import annotations

import copy
from typing import Any

from commands.base import Command


class QuickInitCommand(Command):
    """One-click initialization command - overall snapshot of three managers.

    Process:
    1. Take a before snapshot during construction
    2. Execute the actual auto_complete_project in the handler
    3. Call capture_after() to take after snapshot
    4. Push the command into CommandHistory (no longer call execute())
    5. undo() restores to before; redo (execute) restores to after"""

    label = "Quick initialization"

    def __init__(self, state_mgr: Any, country_mgr: Any, sr_mgr: Any) -> None:
        self._state_mgr = state_mgr
        self._country_mgr = country_mgr
        self._sr_mgr = sr_mgr
        # before snapshot — key internal states of the three managers
        self._before = self._snapshot()
        self._after: dict[str, Any] | None = None

    def _snapshot(self) -> dict[str, Any]:
        snap = {
            "states": copy.deepcopy(getattr(self._state_mgr, "_states", {})),
            "countries": copy.deepcopy(getattr(self._country_mgr, "_countries", {})),
            "state_owner": copy.deepcopy(getattr(self._country_mgr, "_state_owner", {})),
            "regions": copy.deepcopy(getattr(self._sr_mgr, "_regions", {})),
            "sr_next_id": getattr(self._sr_mgr, "_next_id", 1),
        }
        # state_mgr may also have _next_id (depending on the implementation)
        if hasattr(self._state_mgr, "_next_id"):
            snap["state_next_id"] = self._state_mgr._next_id
        return snap

    def capture_after(self) -> None:
        """This method is called after the handler has executed auto_complete_project."""
        self._after = self._snapshot()

    def _restore(self, snap: dict[str, Any]) -> None:
        if hasattr(self._state_mgr, "_states"):
            self._state_mgr._states = copy.deepcopy(snap["states"])
        if hasattr(self._state_mgr, "_next_id") and "state_next_id" in snap:
            self._state_mgr._next_id = snap["state_next_id"]
        if hasattr(self._country_mgr, "_countries"):
            self._country_mgr._countries = copy.deepcopy(snap["countries"])
        if hasattr(self._country_mgr, "_state_owner"):
            self._country_mgr._state_owner = copy.deepcopy(snap["state_owner"])
        if hasattr(self._sr_mgr, "_regions"):
            self._sr_mgr._regions = copy.deepcopy(snap["regions"])
        if hasattr(self._sr_mgr, "_next_id"):
            self._sr_mgr._next_id = snap["sr_next_id"]

    def execute(self) -> None:
        """Revert to after when redoing. The first execution is completed by the handler, and only redo is processed here."""
        if self._after is None:
            return  # capture_after has not been adjusted yet, the first execution path
        self._restore(self._after)

    def undo(self) -> None:
        self._restore(self._before)
