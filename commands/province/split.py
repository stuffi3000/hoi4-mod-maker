"""SplitProvinceCommand — Split a province.

Assigns the specified pixel from the original province to the new province ID."""

from __future__ import annotations

import numpy as np

from commands.base import Command
from domain.map_data import MapData


class SplitProvinceCommand(Command):
    """Split provinces: assign split_pixels from pid to new_pid and fix connectivity."""

    label = "Split province"

    def __init__(
        self,
        map_data: MapData,
        pid: int,
        new_pid: int,
        split_pixels: np.ndarray,
    ) -> None:
        self._map_data = map_data
        self._pid = pid
        self._new_pid = new_pid
        self._split_pixels = split_pixels.copy()
        # Use undo: record the original values of all modified pixels
        self._snapshot: np.ndarray | None = None

    def execute(self) -> None:
        """Split + repair connectivity."""
        pm = self._map_data.province_map
        # Snapshot original state (only the areas that will be modified are recorded)
        affected = self._split_pixels | (pm == self._pid) | (pm == self._new_pid)
        self._snapshot = pm.copy()

        # split
        pm[self._split_pixels] = self._new_pid

        # Fixed connectivity: if multiple pieces are cut, small pieces belong to the other side
        self._fix_connectivity(pm, self._pid, self._new_pid)
        self._fix_connectivity(pm, self._new_pid, self._pid)

    def undo(self) -> None:
        """Revert to the full snapshot before splitting."""
        if self._snapshot is not None:
            # Only restore pixels involved in two provinces
            mask = (self._snapshot == self._pid) | (self._snapshot == self._new_pid) | \
                   (self._map_data.province_map == self._pid) | (self._map_data.province_map == self._new_pid)
            self._map_data.province_map[mask] = self._snapshot[mask]

    @staticmethod
    def _fix_connectivity(pm: np.ndarray, pid: int, other_pid: int) -> None:
        """If pid has multiple connected components, the largest one is retained and the smaller one is returned to other_pid."""
        from scipy.ndimage import label as _label
        mask = pm == pid
        labeled, n_comp = _label(mask)
        if n_comp <= 1:
            return
        sizes = [(int(np.sum(labeled == c)), c) for c in range(1, n_comp + 1)]
        sizes.sort(reverse=True)
        for _, c in sizes[1:]:
            pm[labeled == c] = other_pid
