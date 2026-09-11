"""ResplitStateCommand test - resplit within the state/do not move outside the state/undo/redo"""
import numpy as np
import pytest

from commands.state.resplit import ResplitStateCommand
from domain.managers.state import StateManager, StateData
from data.constants import TILE_LAND


class _FakeMapData:
    def __init__(self, h=48, w=48):
        self.tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
        self.province_map = np.zeros((h, w), dtype=np.int32)


@pytest.fixture
def setup():
    md = _FakeMapData()
    # Left half = province 1 (outside the state); right half top/bottom = province 2/3 (target state)
    md.province_map[:, :20] = 1
    md.province_map[:24, 24:] = 2
    md.province_map[24:, 24:] = 3
    # There is an unallocated band (x 20~23) with pm==0 in the middle, simulating a newly drawn land
    mgr = StateManager()
    mgr._states[7] = StateData(id=7, provinces=[2, 3])
    mgr._province_to_state = {2: 7, 3: 7}
    mgr._states[7].victory_points = {2: 5}
    mgr._states[7].vp_names = {2: "Oldtown"}
    return md, mgr


def test_resplit_only_inside_state(setup):
    md, mgr = setup
    old_pm = md.province_map.copy()
    inside = np.isin(old_pm, [2, 3])

    cmd = ResplitStateCommand(md, mgr, 7, 6)
    cmd.execute()

    # None of the out-of-state pixels (province 1 + unallocated zone) changed
    assert (md.province_map[~inside] == old_pm[~inside]).all()
    # Replace all states with new IDs (> 3)
    new_ids = np.unique(md.province_map[inside])
    assert (new_ids > 3).all()
    # The new province is returned to the state, the reverse lookup table is synchronized, and the VP is cleared
    state = mgr.get_state(7)
    assert sorted(state.provinces) == sorted(int(i) for i in new_ids)
    assert all(mgr.get_state_of_province(int(i)) == 7 for i in new_ids)
    assert state.victory_points == {} and state.vp_names == {}


def test_resplit_undo_redo(setup):
    md, mgr = setup
    old_pm = md.province_map.copy()

    cmd = ResplitStateCommand(md, mgr, 7, 6)
    cmd.execute()
    after_pm = md.province_map.copy()
    after_provinces = list(mgr.get_state(7).provinces)

    cmd.undo()
    assert (md.province_map == old_pm).all()
    state = mgr.get_state(7)
    assert sorted(state.provinces) == [2, 3]
    assert state.victory_points == {2: 5}
    assert mgr.get_state_of_province(2) == 7

    cmd.execute()  # redo playback, the result is exactly the same as the first time
    assert (md.province_map == after_pm).all()
    assert list(mgr.get_state(7).provinces) == after_provinces
