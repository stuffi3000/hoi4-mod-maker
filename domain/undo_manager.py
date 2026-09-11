"""Undo/Redo Manager — Command history based on compressed snapshots
Support for local differential storage of numpy arrays"""
import zlib
import numpy as np


class UndoStep:
    """An undo step that stores the compressed data before the operation"""
    __slots__ = ("description", "snapshots")

    def __init__(self, description: str, snapshots: list[tuple[str, bytes, tuple]]):
        """
        snapshots: [(array_name, compressed_data, shape_and_dtype), ...]
        """
        self.description = description
        self.snapshots = snapshots


class UndoManager:
    """Manage undo/redo stack"""

    def __init__(self, max_steps: int = 30):
        self._max_steps = max_steps
        self._undo_stack: list[UndoStep] = []
        self._redo_stack: list[UndoStep] = []
        # The operation currently being logged (mousePress to mouseRelease)
        self._pending: dict[str, tuple[bytes, tuple]] | None = None
        self._pending_desc: str = ""

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def begin_stroke(self, description: str, arrays: dict[str, np.ndarray]) -> None:
        """Start a brush operation and record a snapshot before the operation"""
        self._pending_desc = description
        self._pending = {}
        for name, arr in arrays.items():
            compressed = zlib.compress(arr.tobytes(), level=1)
            self._pending[name] = (compressed, (arr.shape, arr.dtype))

    def end_stroke(self, arrays: dict[str, np.ndarray]) -> None:
        """End the brush operation, compare and save the differences"""
        if self._pending is None:
            return

        # Check if there are any actual changes
        changed = False
        for name, arr in arrays.items():
            if name in self._pending:
                old_data = zlib.decompress(self._pending[name][0])
                shape, dtype = self._pending[name][1]
                old_arr = np.frombuffer(old_data, dtype=dtype).reshape(shape)
                if not np.array_equal(old_arr, arr):
                    changed = True
                    break

        if changed:
            snapshots = [
                (name, data, info)
                for name, (data, info) in self._pending.items()
            ]
            step = UndoStep(self._pending_desc, snapshots)
            self._undo_stack.append(step)
            if len(self._undo_stack) > self._max_steps:
                self._undo_stack.pop(0)
            self._redo_stack.clear()

        self._pending = None

    def push_snapshot(self, description: str, arrays: dict[str, np.ndarray]) -> None:
        """Push directly into a full snapshot (for non-brush operations like merge/cut/fill)"""
        snapshots = []
        for name, arr in arrays.items():
            compressed = zlib.compress(arr.tobytes(), level=1)
            snapshots.append((name, compressed, (arr.shape, arr.dtype)))

        step = UndoStep(description, snapshots)
        self._undo_stack.append(step)
        if len(self._undo_stack) > self._max_steps:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self, current_arrays: dict[str, np.ndarray]) -> dict[str, np.ndarray] | None:
        """Undo a step.
        current_arrays: Reference to each current array (used to save to redo stack)
        Returns the restored array dictionary, or None (no undo)"""
        if not self._undo_stack:
            return None

        step = self._undo_stack.pop()

        # Save current state to redo stack
        redo_snapshots = []
        for name, _, _ in step.snapshots:
            if name in current_arrays:
                arr = current_arrays[name]
                compressed = zlib.compress(arr.tobytes(), level=1)
                redo_snapshots.append((name, compressed, (arr.shape, arr.dtype)))
        self._redo_stack.append(UndoStep(step.description, redo_snapshots))

        # Restore old data
        result = {}
        for name, compressed, (shape, dtype) in step.snapshots:
            data = zlib.decompress(compressed)
            result[name] = np.frombuffer(data, dtype=dtype).reshape(shape).copy()
        return result

    def redo(self, current_arrays: dict[str, np.ndarray]) -> dict[str, np.ndarray] | None:
        """Redo the step.
        Returns the restored array dictionary, or None (no redo)"""
        if not self._redo_stack:
            return None

        step = self._redo_stack.pop()

        # Save current state to undo stack
        undo_snapshots = []
        for name, _, _ in step.snapshots:
            if name in current_arrays:
                arr = current_arrays[name]
                compressed = zlib.compress(arr.tobytes(), level=1)
                undo_snapshots.append((name, compressed, (arr.shape, arr.dtype)))
        self._undo_stack.append(UndoStep(step.description, undo_snapshots))

        # Recover data
        result = {}
        for name, compressed, (shape, dtype) in step.snapshots:
            data = zlib.decompress(compressed)
            result[name] = np.frombuffer(data, dtype=dtype).reshape(shape).copy()
        return result

    def clear(self) -> None:
        """Clear all history"""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._pending = None
