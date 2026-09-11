"""PaintRiverCommand — Brush to draw river pixels.

Stores changing pixel delta, supporting continuous stroke merging."""

from __future__ import annotations

from commands.base import Command
from domain.map_data import MapData


class PaintRiverCommand(Command):
    """The brush draws river_map pixels."""

    label = "Paint river"

    def __init__(
        self,
        map_data: MapData,
        changes: dict[tuple[int, int], int],
    ) -> None:
        """Parameters:
            map_data: map data object
            changes: {(y, x): new_value} New river pixel value to write"""
        self._map_data = map_data
        self._changes = dict(changes)
        self._old_values: dict[tuple[int, int], int] = {}

    def execute(self) -> None:
        """Save the old value and write the new value."""
        river_map = self._map_data.river_map
        old = {}
        for (y, x), new_val in self._changes.items():
            old[(y, x)] = int(river_map[y, x])
            river_map[y, x] = new_val
        self._old_values.update(old)

    def undo(self) -> None:
        """Restore old value."""
        river_map = self._map_data.river_map
        for (y, x), old_val in self._old_values.items():
            river_map[y, x] = old_val

    def can_merge_with(self, other: Command) -> bool:
        """Continuous river strokes can be merged."""
        return isinstance(other, PaintRiverCommand)

    def merge(self, other: Command) -> None:
        """Incorporate other's changes."""
        if not isinstance(other, PaintRiverCommand):
            raise TypeError("Only commands of the same type can be merged")
        for pos, new_val in other._changes.items():
            if pos not in self._old_values:
                self._old_values[pos] = other._old_values.get(pos, new_val)
            self._changes[pos] = new_val
