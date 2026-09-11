"""ManagerSnapshotCommand — Generic manager field snapshot undo/redo.

Commands used for automatic grouping of states, automatic strategic areas, and other batch modification of internal fields of the manager.
Retain the identity of the dict object (clear + update), do not replace the reference, and avoid the invalidation of old external references."""

from __future__ import annotations

import copy
from typing import Any

from commands.base import Command


class ManagerSnapshotCommand(Command):
    """Generic manager state snapshot command.

    Usage:
    1. cmd = ManagerSnapshotCommand("Auto group states", mgr, ["_states", "_next_id"])
    2. handler performs actual operations (modify mgr)
    3. cmd.capture_after()
    4. history._undo_stack.append(cmd)"""

    def __init__(self, label: str, manager: Any, field_names: list[str]) -> None:
        self.label = label
        self._manager = manager
        self._fields = field_names
        self._before = self._snapshot()
        self._after: dict[str, Any] | None = None

    def _snapshot(self) -> dict[str, Any]:
        return {f: copy.deepcopy(getattr(self._manager, f)) for f in self._fields}

    def capture_after(self) -> None:
        self._after = self._snapshot()

    def _restore(self, snap: dict[str, Any]) -> None:
        for field, val in snap.items():
            current = getattr(self._manager, field, None)
            new_val = copy.deepcopy(val)
            # dict maintains object identity (clear + update), others are directly setattr
            if isinstance(current, dict) and isinstance(new_val, dict):
                current.clear()
                current.update(new_val)
            elif isinstance(current, set) and isinstance(new_val, set):
                current.clear()
                current.update(new_val)
            elif isinstance(current, list) and isinstance(new_val, list):
                current.clear()
                current.extend(new_val)
            else:
                setattr(self._manager, field, new_val)

    def execute(self) -> None:
        """redo — Revert to after. The first execution is done by the handler."""
        if self._after is None:
            return
        self._restore(self._after)

    def undo(self) -> None:
        self._restore(self._before)
