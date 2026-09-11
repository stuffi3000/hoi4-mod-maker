"""readiness_service test — Business rules for readiness checks.

This set of standards is shared by the export preflight and production progress panels (M2), and behavioral changes will affect both at the same time."""

from types import SimpleNamespace

import numpy as np
import pytest

from services.readiness_service import check_project_readiness, CheckItem
from domain.managers.state import StateManager, StateData
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from domain.managers.strategic_region import StrategicRegionManager
from data.constants import TILE_LAND, TILE_SEA


def _map_source(h=8, w=16):
    """Minimum map data source: upper half of the sea, lower half of the land, two provinces."""
    tile_map = np.full((h, w), TILE_SEA, dtype=np.uint8)
    tile_map[h // 2:, :] = TILE_LAND
    province_map = np.zeros((h, w), dtype=np.int32)
    province_map[:h // 2, :] = 1                   # maritime provinces
    province_map[h // 2:, :] = 2                   # mainland provinces
    terrain_map = np.ones((h, w), dtype=np.uint8)
    height_map = np.full((h, w), 90, dtype=np.uint8)
    height_map[h // 2:, :] = 120
    return SimpleNamespace(
        tile_map=tile_map, province_map=province_map,
        terrain_map=terrain_map, height_map=height_map,
    )


def _project(with_state=True, with_country=True):
    state_mgr = StateManager()
    country_mgr = CountryManager()
    if with_state:
        state_mgr._states[1] = StateData(
            id=1, name="S1", provinces=[2], owner_tag="TST")
        state_mgr._province_to_state = {2: 1}
        state_mgr._next_id = 2
    if with_country:
        country_mgr.create_country("TST", "Test", (10, 20, 30))
        country_mgr.set_capital("TST", 2)
        country_mgr.assign_state(1, "TST")
    sr_mgr = StrategicRegionManager()
    sr_mgr.create_region()
    cont_mgr = ContinentManager()
    return SimpleNamespace(
        state_mgr=state_mgr, country_mgr=country_mgr,
        strategic_region_mgr=sr_mgr, continent_mgr=cont_mgr,
        assets={},
    )


def _by_status(items: list[CheckItem]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i.status] = out.get(i.status, 0) + 1
    return out


def test_empty_map_short_circuits():
    """There is no province: only one missing is reported, and no follow-up checks are performed."""
    src = _map_source()
    src.province_map[:] = 0
    items = check_project_readiness(_project(), src)
    assert len(items) == 1
    assert items[0].status == "missing"


def test_complete_project_all_ok():
    """Complete items: There are no missing items."""
    items = check_project_readiness(_project(), _map_source())
    statuses = _by_status(items)
    assert statuses.get("missing", 0) == 0


def test_missing_state_and_country_flagged_auto_fixable():
    """Missing State/Country: Report missing and the mark can be automatically completed."""
    items = check_project_readiness(
        _project(with_state=False, with_country=False), _map_source())
    missing = [i for i in items if i.status == "missing"]
    assert len(missing) >= 2
    assert all(i.can_auto for i in missing)


def test_id_gap_reported_as_warning():
    """Province number hole: warning (export will be automatically compacted and not blocked)."""
    src = _map_source()
    src.province_map[src.province_map == 2] = 9   # Creates 2-8 holes
    proj = _project(with_state=False, with_country=False)
    items = check_project_readiness(proj, src)
    assert items[0].status == "warning"


def test_accepts_mapdata_as_source():
    """MapData objects are available directly (the panel side does not have to go through the canvas)."""
    import data.constants as constants
    from data.constants import set_map_size
    from domain.map_data import MapData

    old = (constants.MAP_WIDTH, constants.MAP_HEIGHT)
    set_map_size(16, 8)
    try:
        md = MapData()
        src = _map_source()
        md.tile_map[:] = src.tile_map
        md.province_map[:] = src.province_map
        md.terrain_map[:] = src.terrain_map
        md.height_map[:] = src.height_map
        items = check_project_readiness(_project(), md)
        assert _by_status(items).get("missing", 0) == 0
    finally:
        set_map_size(*old)
