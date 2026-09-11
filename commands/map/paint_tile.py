"""PaintTileCommand — Brushes for painting land/ocean/lake tiles.

Store the changed pixel delta: {(y, x): new_value}, record the old value when executing, and restore it when undo.
Supports continuous stroke merging (can_merge_with / merge)."""

from __future__ import annotations

from commands.base import Command
from domain.map_data import MapData


class PaintTileCommand(Command):
    """The brush draws tile_map pixels."""

    label = "Paint tiles"

    def __init__(
        self,
        map_data: MapData,
        changes: dict[tuple[int, int], int],
    ) -> None:
        """Parameters:
            map_data: map data object
            changes: {(y, x): new_value} The new pixel value to write"""
        self._map_data = map_data
        self._changes = dict(changes)  # defensive copying
        self._old_values: dict[tuple[int, int], int] = {}

    def execute(self) -> None:
        """Save the old value and write the new value."""
        tile_map = self._map_data.tile_map
        old = {}
        for (y, x), new_val in self._changes.items():
            old[(y, x)] = int(tile_map[y, x])
            tile_map[y, x] = new_val
        self._old_values.update(old)

    def undo(self) -> None:
        """Restore old value."""
        tile_map = self._map_data.tile_map
        for (y, x), old_val in self._old_values.items():
            tile_map[y, x] = old_val

    def can_merge_with(self, other: Command) -> bool:
        """Continuous brush strokes can be merged."""
        return isinstance(other, PaintTileCommand)

    def merge(self, other: Command) -> None:
        """Incorporate other's changes.

        For overlapping pixels, retain the old_value of self (the oldest old value),
        Use other's new_value (the latest new value)."""
        if not isinstance(other, PaintTileCommand):
            raise TypeError("Only commands of the same type can be merged")
        for pos, new_val in other._changes.items():
            if pos not in self._old_values:
                # self has not touched this pixel, get the old value from other
                self._old_values[pos] = other._old_values.get(pos, new_val)
            # The new value is always the latest
            self._changes[pos] = new_val
