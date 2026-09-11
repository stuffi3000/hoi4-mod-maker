"""Undoable compressed snapshots for brush-based map edits."""

from __future__ import annotations

import zlib

import numpy as np

from commands.base import Command


class BrushStrokeCommand(Command):
    """Restore named NumPy arrays from compressed before-and-after snapshots."""

    label = "Brush stroke"

    def __init__(
        self,
        description: str,
        before_snapshots: dict[str, tuple[bytes, tuple]],
        after_snapshots: dict[str, tuple[bytes, tuple]],
    ) -> None:
        """Store snapshots and initialize the registry of live target arrays."""
        self.label = description
        self._before = before_snapshots
        self._after = after_snapshots
        # Targets are attached later because the command is created before the canvas update.
        self._target_arrays: dict[str, np.ndarray] = {}

    def set_target_arrays(self, arrays: dict[str, np.ndarray]) -> None:
        """Attach the live arrays that future execute and undo calls should update."""
        self._target_arrays = arrays

    def execute(self) -> None:
        """Restore the after snapshot into every attached target array."""
        for name, (compressed, (shape, dtype)) in self._after.items():
            if name in self._target_arrays:
                data = zlib.decompress(compressed)
                restored = np.frombuffer(data, dtype=dtype).reshape(shape)
                self._target_arrays[name][:] = restored

    def undo(self) -> None:
        """Restore the before snapshot into every attached target array."""
        for name, (compressed, (shape, dtype)) in self._before.items():
            if name in self._target_arrays:
                data = zlib.decompress(compressed)
                restored = np.frombuffer(data, dtype=dtype).reshape(shape)
                self._target_arrays[name][:] = restored

    @staticmethod
    def snapshot_arrays(arrays: dict[str, np.ndarray]) -> dict[str, tuple[bytes, tuple]]:
        """Compress a copy of each named array for a command snapshot."""
        result = {}
        for name, arr in arrays.items():
            compressed = zlib.compress(arr.tobytes(), level=1)
            result[name] = (compressed, (arr.shape, arr.dtype))
        return result

    @staticmethod
    def has_changes(
        before: dict[str, tuple[bytes, tuple]],
        after_arrays: dict[str, np.ndarray],
    ) -> bool:
        """Return whether any current array differs from its saved before snapshot."""
        for name, (compressed, (shape, dtype)) in before.items():
            if name in after_arrays:
                old_data = zlib.decompress(compressed)
                old_arr = np.frombuffer(old_data, dtype=dtype).reshape(shape)
                if not np.array_equal(old_arr, after_arrays[name]):
                    return True
        return False
