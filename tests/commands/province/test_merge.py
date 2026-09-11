"""MergeProvincesCommand unit test."""

import numpy as np
import pytest

from domain.map_data import MapData
from commands.province.merge import MergeProvincesCommand


def _make_map_data(h: int = 4, w: int = 4) -> MapData:
    """Create a small MapData for testing."""
    md = MapData.__new__(MapData)
    md.tile_map = np.ones((h, w), dtype=np.uint8)  # All land
    md.province_map = np.zeros((h, w), dtype=np.int32)
    md.terrain_map = np.zeros((h, w), dtype=np.uint8)
    md.height_map = np.full((h, w), 40, dtype=np.uint8)
    md.river_map = np.full((h, w), 255, dtype=np.uint8)
    md.provincial_terrain = {}
    return md


class TestMergeProvincesCommand:
    """MergeProvincesCommand test."""

    def test_merge_changes_pixels(self) -> None:
        """execute should change pixels from removed provinces to retain province IDs."""
        md = _make_map_data()
        # Set two provinces: pid=1 occupies the left half, pid=2 occupies the right half
        md.province_map[:, :2] = 1
        md.province_map[:, 2:] = 2

        cmd = MergeProvincesCommand(md, pid_keep=1, pid_remove=2)
        cmd.execute()

        # All pixels should have pid=1
        assert (md.province_map[:, 2:] == 1).all()
        assert (md.province_map[:, :2] == 1).all()

    def test_undo_restores_pixels(self) -> None:
        """undo should restore the pixels of merged provinces."""
        md = _make_map_data()
        md.province_map[:, :2] = 1
        md.province_map[:, 2:] = 2

        original = md.province_map.copy()

        cmd = MergeProvincesCommand(md, pid_keep=1, pid_remove=2)
        cmd.execute()

        # After merging, pid=2 disappears
        assert not (md.province_map == 2).any()

        cmd.undo()

        # After recovery the right half should be back to pid=2
        assert (md.province_map[:, 2:] == 2).all()
        assert (md.province_map[:, :2] == 1).all()


class TestMergeStrategicRegionCleanup:
    """After merge, pid_remove must be removed from strategic_region, otherwise the new province will inherit the old region when the reuse ID is cut."""

    def test_pid_remove_cleared_from_region_on_execute(self) -> None:
        from domain.managers.strategic_region import StrategicRegionManager

        md = _make_map_data()
        md.province_map[:, :2] = 1
        md.province_map[:, 2:] = 2

        sr = StrategicRegionManager()
        r = sr.create_region(name="region_A")
        r.province_ids = [1, 2]

        cmd = MergeProvincesCommand(
            md, pid_keep=1, pid_remove=2, strategic_region_mgr=sr
        )
        cmd.execute()

        assert 2 not in sr.get(r.id).province_ids
        assert 1 in sr.get(r.id).province_ids

    def test_undo_restores_pid_to_region(self) -> None:
        from domain.managers.strategic_region import StrategicRegionManager

        md = _make_map_data()
        md.province_map[:, :2] = 1
        md.province_map[:, 2:] = 2

        sr = StrategicRegionManager()
        r = sr.create_region(name="region_A")
        r.province_ids = [1, 2]

        cmd = MergeProvincesCommand(
            md, pid_keep=1, pid_remove=2, strategic_region_mgr=sr
        )
        cmd.execute()
        cmd.undo()

        assert 2 in sr.get(r.id).province_ids


class TestMergeCapitalMigration:
    """If merge swallows the capital of a country, the capital must be moved, otherwise the capital points to the dead ID → the game will crash when starting."""

    def test_capital_migrates_to_pid_keep_when_same_country(self) -> None:
        from domain.managers.state import StateManager
        from domain.managers.country import CountryManager

        md = _make_map_data()
        md.province_map[:, :2] = 1
        md.province_map[:, 2:] = 2

        state_mgr = StateManager()
        s = state_mgr.create_state()
        state_mgr.assign_province(1, s.id)
        state_mgr.assign_province(2, s.id)

        country_mgr = CountryManager()
        country_mgr.create_country("AAA", name="A", color=(1, 2, 3))
        country_mgr.assign_state(s.id, "AAA")
        country_mgr.set_capital("AAA", 2)  # capital = pid_remove

        cmd = MergeProvincesCommand(
            md, pid_keep=1, pid_remove=2,
            state_mgr=state_mgr, country_mgr=country_mgr,
        )
        cmd.execute()

        # The capital is moved to pid_keep (same country, physically takes over the pixels of pid_remove)
        assert country_mgr.get_country("AAA").capital == 1

    def test_undo_restores_capital(self) -> None:
        from domain.managers.state import StateManager
        from domain.managers.country import CountryManager

        md = _make_map_data()
        md.province_map[:, :2] = 1
        md.province_map[:, 2:] = 2

        state_mgr = StateManager()
        s = state_mgr.create_state()
        state_mgr.assign_province(1, s.id)
        state_mgr.assign_province(2, s.id)

        country_mgr = CountryManager()
        country_mgr.create_country("AAA", name="A", color=(1, 2, 3))
        country_mgr.assign_state(s.id, "AAA")
        country_mgr.set_capital("AAA", 2)

        cmd = MergeProvincesCommand(
            md, pid_keep=1, pid_remove=2,
            state_mgr=state_mgr, country_mgr=country_mgr,
        )
        cmd.execute()
        cmd.undo()

        assert country_mgr.get_country("AAA").capital == 2

    def test_no_capital_change_when_pid_remove_not_capital(self) -> None:
        from domain.managers.state import StateManager
        from domain.managers.country import CountryManager

        md = _make_map_data()
        md.province_map[:, :2] = 1
        md.province_map[:, 2:] = 2

        state_mgr = StateManager()
        s = state_mgr.create_state()
        state_mgr.assign_province(1, s.id)
        state_mgr.assign_province(2, s.id)

        country_mgr = CountryManager()
        country_mgr.create_country("AAA", name="A", color=(1, 2, 3))
        country_mgr.assign_state(s.id, "AAA")
        country_mgr.set_capital("AAA", 1)  # capital = pid_keep, not pid_remove

        cmd = MergeProvincesCommand(
            md, pid_keep=1, pid_remove=2,
            state_mgr=state_mgr, country_mgr=country_mgr,
        )
        cmd.execute()

        assert country_mgr.get_country("AAA").capital == 1
