"""SetVPCommand — Set/remove victory points."""

from __future__ import annotations

from commands.base import Command


class SetVPCommand(Command):
    """Sets or removes a province's Victory Points."""

    label = "Set victory point"

    def __init__(
        self,
        state_mgr,
        pid: int,
        old_vp: int | None,
        new_vp: int | None,
    ) -> None:
        """Parameters:
            state_mgr: StateManager instance
            pid: province ID
            old_vp: old VP value (None=no VP)
            new_vp: new VP value (None=remove VP)"""
        self._state_mgr = state_mgr
        self._pid = pid
        self._old_vp = old_vp
        self._new_vp = new_vp

    def execute(self) -> None:
        """Set or remove VP."""
        if self._new_vp is not None:
            self._state_mgr.set_vp(self._pid, self._new_vp)
        else:
            self._state_mgr.remove_vp(self._pid)

    def undo(self) -> None:
        """Restore old VP."""
        if self._old_vp is not None:
            self._state_mgr.set_vp(self._pid, self._old_vp)
        else:
            self._state_mgr.remove_vp(self._pid)
