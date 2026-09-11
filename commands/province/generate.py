"""GenerateProvincesCommand — Generate provinces (stores a zlib-compressed snapshot of the old province_map).

Since province_map is large (5632x2048 int32 = ~44MB), old values ​​are stored using zlib compression."""

from __future__ import annotations

import zlib

import numpy as np

from commands.base import Command
from domain.map_data import MapData


class GenerateProvincesCommand(Command):
    """Generate provinces, store full old province_map (zlib compressed)."""

    label = "Generate provinces"

    def __init__(
        self,
        map_data: MapData,
        new_province_map: np.ndarray,
        new_count: int,
    ) -> None:
        """Parameters:
            map_data: map data object
            new_province_map: new province map (int32 array)
            new_count: new total number of provinces"""
        self._map_data = map_data
        self._new_map = new_province_map.copy()
        self._new_count = new_count
        # Lazy saving of old values (compression on execute)
        self._old_map_compressed: bytes = b""
        self._old_shape: tuple[int, ...] = ()
        self._old_dtype: np.dtype = np.dtype(np.int32)

    def execute(self) -> None:
        """Save old province_map compressed and write new values."""
        old_map = self._map_data.province_map
        self._old_shape = old_map.shape
        self._old_dtype = old_map.dtype
        self._old_map_compressed = zlib.compress(old_map.tobytes(), level=1)
        self._map_data.province_map[:] = self._new_map

    def undo(self) -> None:
        """Unzip and restore the old province_map."""
        raw = zlib.decompress(self._old_map_compressed)
        old_map = np.frombuffer(raw, dtype=self._old_dtype).reshape(self._old_shape)
        self._map_data.province_map[:] = old_map
