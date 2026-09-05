"""Undoable replacement of one or more generated map layers."""
from __future__ import annotations

import zlib

import numpy as np

from commands.base import Command
from domain.map_data import MapData


class ApplyReferenceLayersCommand(Command):
    """Apply full-size reference-derived arrays as a single undo step."""

    def __init__(self, map_data: MapData, layers: dict[str, np.ndarray], label: str) -> None:
        self.label = label
        self._map_data = map_data
        self._new: dict[str, tuple[bytes, tuple[int, ...], np.dtype]] = {}
        self._old: dict[str, tuple[bytes, tuple[int, ...], np.dtype]] = {}
        self._captured = False
        self._old_tile_snapshot: np.ndarray | None = None
        self._old_tile_snapshot_was_none = map_data.tile_snapshot is None
        self._sets_tile_snapshot = "province_map" in layers
        for name, value in layers.items():
            current = getattr(map_data, name, None)
            if not isinstance(current, np.ndarray):
                raise ValueError(f"Unknown map layer: {name}")
            array = np.asarray(value, dtype=current.dtype)
            if array.shape != current.shape:
                raise ValueError(f"Layer {name} has shape {array.shape}, expected {current.shape}")
            self._new[name] = (zlib.compress(array.tobytes(), 1), array.shape, array.dtype)

    @staticmethod
    def _decode(snapshot: tuple[bytes, tuple[int, ...], np.dtype]) -> np.ndarray:
        compressed, shape, dtype = snapshot
        return np.frombuffer(zlib.decompress(compressed), dtype=dtype).reshape(shape)

    def execute(self) -> None:
        if not self._captured:
            for name in self._new:
                array = getattr(self._map_data, name)
                self._old[name] = (zlib.compress(array.tobytes(), 1), array.shape, array.dtype)
            if self._sets_tile_snapshot and self._map_data.tile_snapshot is not None:
                self._old_tile_snapshot = self._map_data.tile_snapshot.copy()
            self._captured = True
        for name, snapshot in self._new.items():
            getattr(self._map_data, name)[:] = self._decode(snapshot)
        if "province_map" in self._new:
            self._map_data.tile_snapshot = self._map_data.tile_map.copy()
            self._map_data.invalidate_centroid_cache()

    def undo(self) -> None:
        for name, snapshot in self._old.items():
            getattr(self._map_data, name)[:] = self._decode(snapshot)
        if "province_map" in self._old:
            self._map_data.tile_snapshot = (
                None if self._old_tile_snapshot_was_none
                else self._old_tile_snapshot.copy()
            )
            self._map_data.invalidate_centroid_cache()
