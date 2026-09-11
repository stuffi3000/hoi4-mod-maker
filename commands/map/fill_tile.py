"""FillTileCommand — Flood fill tile_map.

Use a numpy bool mask to mark the affected area, storing the old value delta."""

from __future__ import annotations

import numpy as np

from commands.base import Command
from domain.map_data import MapData


class FillTileCommand(Command):
    """Flood fills tile_map."""

    label = "Fill tiles"

    def __init__(
        self,
        map_data: MapData,
        fill_mask: np.ndarray,
        fill_value: int,
    ) -> None:
        """Parameters:
            map_data: map data object
            fill_mask: bool array, True pixels will be filled
            fill_value: fill value"""
        self._map_data = map_data
        self._fill_mask = fill_mask.copy()
        self._fill_value = fill_value
        # Only store old values that have been changed (compressed storage)
        self._old_values: np.ndarray | None = None

    def execute(self) -> None:
        """Save the old value of the mask area and write the fill value."""
        tile_map = self._map_data.tile_map
        self._old_values = tile_map[self._fill_mask].copy()
        tile_map[self._fill_mask] = self._fill_value

    def undo(self) -> None:
        """Restore the old value of the mask area."""
        if self._old_values is not None:
            self._map_data.tile_map[self._fill_mask] = self._old_values
