"""SetHeightCommand — Set height value by province mask."""

from __future__ import annotations

import numpy as np

from commands.base import Command
from domain.map_data import MapData


class SetHeightCommand(Command):
    """Set height_map in batches by province mask."""

    label = "Set height"

    def __init__(
        self,
        map_data: MapData,
        province_mask: np.ndarray,
        new_height_value: int,
    ) -> None:
        """Parameters:
            map_data: map data object
            province_mask: bool array, True pixels will be modified
            new_height_value: new height value (0-255)"""
        self._map_data = map_data
        self._mask = province_mask.copy()
        self._new_height = new_height_value
        self._old_heights: np.ndarray | None = None

    def execute(self) -> None:
        """Save the old height and write the new value."""
        height_map = self._map_data.height_map
        self._old_heights = height_map[self._mask].copy()
        height_map[self._mask] = self._new_height

    def undo(self) -> None:
        """Restore old height."""
        if self._old_heights is not None:
            self._map_data.height_map[self._mask] = self._old_heights
