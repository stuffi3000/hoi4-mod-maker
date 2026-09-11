"""PaintTileCommand unit test."""

import numpy as np
import pytest

from domain.map_data import MapData
from commands.map.paint_tile import PaintTileCommand


def _make_map_data(h: int = 4, w: int = 4) -> MapData:
    """Create a small MapData for testing."""
    md = MapData.__new__(MapData)
    md.tile_map = np.zeros((h, w), dtype=np.uint8)
    md.province_map = np.zeros((h, w), dtype=np.int32)
    md.terrain_map = np.zeros((h, w), dtype=np.uint8)
    md.height_map = np.full((h, w), 40, dtype=np.uint8)
    md.river_map = np.full((h, w), 255, dtype=np.uint8)
    md.provincial_terrain = {}
    return md


class TestPaintTileCommand:
    """PaintTileCommand test."""

    def test_execute_changes_pixels(self) -> None:
        """execute should modify the corresponding pixels of tile_map."""
        md = _make_map_data()
        changes = {(0, 0): 1, (1, 2): 2, (3, 3): 1}
        cmd = PaintTileCommand(md, changes)
        cmd.execute()

        assert md.tile_map[0, 0] == 1
        assert md.tile_map[1, 2] == 2
        assert md.tile_map[3, 3] == 1
        # Unmodified pixels remain unchanged
        assert md.tile_map[0, 1] == 0

    def test_undo_restores_old_values(self) -> None:
        """undo should restore the value before modification."""
        md = _make_map_data()
        md.tile_map[0, 0] = 5
        md.tile_map[1, 1] = 7

        changes = {(0, 0): 1, (1, 1): 2}
        cmd = PaintTileCommand(md, changes)
        cmd.execute()

        assert md.tile_map[0, 0] == 1
        assert md.tile_map[1, 1] == 2

        cmd.undo()

        assert md.tile_map[0, 0] == 5
        assert md.tile_map[1, 1] == 7

    def test_can_merge_with_same_type(self) -> None:
        """can_merge_with should return True for the same type."""
        md = _make_map_data()
        cmd1 = PaintTileCommand(md, {(0, 0): 1})
        cmd2 = PaintTileCommand(md, {(1, 1): 2})

        assert cmd1.can_merge_with(cmd2) is True

    def test_can_merge_with_different_type(self) -> None:
        """can_merge_with should return False for different types."""
        from commands.base import Command

        md = _make_map_data()
        cmd1 = PaintTileCommand(md, {(0, 0): 1})

        class DummyCommand(Command):
            def execute(self) -> None: ...
            def undo(self) -> None: ...

        cmd2 = DummyCommand()
        assert cmd1.can_merge_with(cmd2) is False

    def test_merge_combines_changes(self) -> None:
        """merge should merge the changes from the two commands, retaining the oldest value."""
        md = _make_map_data()
        md.tile_map[0, 0] = 10
        md.tile_map[1, 1] = 20

        cmd1 = PaintTileCommand(md, {(0, 0): 1})
        cmd1.execute()

        cmd2 = PaintTileCommand(md, {(0, 0): 3, (1, 1): 4})
        cmd2.execute()

        cmd1.merge(cmd2)

        # After merging, undo should be restored to the original value.
        cmd1.undo()
        assert md.tile_map[0, 0] == 10  # oldest old value
        assert md.tile_map[1, 1] == 20  # The old value recorded by cmd2

    def test_execute_is_reentrant(self) -> None:
        """execute can be reentrant (no error will occur if redo is called again)."""
        md = _make_map_data()
        changes = {(0, 0): 1}
        cmd = PaintTileCommand(md, changes)

        cmd.execute()
        assert md.tile_map[0, 0] == 1
        cmd.undo()
        assert md.tile_map[0, 0] == 0
        cmd.execute()
        assert md.tile_map[0, 0] == 1
