"""Undoable commands for transforming rectangular regions of the tile map."""

from __future__ import annotations

import numpy as np

from commands.base import Command
from domain.map_data import MapData


class TransformCommand(Command):
    """Apply a rectangular map transformation and support undo."""

    label = "Transform region"

    def __init__(
        self,
        map_data: MapData,
        old_region: tuple[tuple[int, int, int, int], np.ndarray],
        new_region: tuple[tuple[int, int, int, int], np.ndarray],
    ) -> None:
        """Capture the original and transformed rectangular map regions."""
        self._map_data = map_data
        self._old_bbox, self._old_data = old_region
        self._new_bbox, self._new_data = new_region
        # Copy both snapshots so later canvas edits cannot mutate command history.
        self._old_data = self._old_data.copy()
        self._new_data = self._new_data.copy()

    def _apply_region(
        self, bbox: tuple[int, int, int, int], data: np.ndarray
    ) -> None:
        """Write a saved rectangular region back to the tile map."""
        y_min, x_min, y_max, x_max = bbox
        self._map_data.tile_map[y_min:y_max, x_min:x_max] = data

    def execute(self) -> None:
        """Apply the transformed region."""
        self._apply_region(self._new_bbox, self._new_data)

    def undo(self) -> None:
        """Restore the region that existed before the transformation."""
        self._apply_region(self._old_bbox, self._old_data)
