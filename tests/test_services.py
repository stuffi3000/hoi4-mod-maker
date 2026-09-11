"""services/* tests."""

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolate_language():
    """Service-message assertions must not depend on another test's locale."""
    from ui.i18n import get_language, set_language
    previous = get_language()
    set_language("en")
    try:
        yield
    finally:
        set_language(previous)


def test_terrain_service_auto_terrain():
    from services.terrain_service import auto_terrain
    from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
    from data.terrain_types import DEFAULT_TERRAIN_FOR_TILE, TERRAIN_PALETTE_INDEX

    tm = np.array([
        [TILE_LAND, TILE_SEA, TILE_LAKE],
        [TILE_LAND, TILE_SEA, TILE_LAND],
    ], dtype=np.uint8)
    terrain = auto_terrain(tm)
    assert terrain.shape == tm.shape
    # The terrain value for land pixels must be the palette index corresponding to DEFAULT_TERRAIN_FOR_TILE[LAND]
    expected_land = TERRAIN_PALETTE_INDEX[DEFAULT_TERRAIN_FOR_TILE[TILE_LAND]]
    assert terrain[0, 0] == expected_land


def test_terrain_service_auto_height_range():
    from services.terrain_service import auto_height
    from data.constants import (
        MAP_WIDTH, MAP_HEIGHT, TILE_LAND, TILE_SEA, SEA_LEVEL,
    )
    tm = np.full((MAP_HEIGHT, MAP_WIDTH), TILE_LAND, dtype=np.uint8)
    tm[0, :] = TILE_SEA
    tm[-1, :] = TILE_SEA
    hm = auto_height(tm)
    assert hm.dtype == np.uint8
    assert hm.min() >= 0
    assert hm.max() <= 255
    # Land center height should be > sea level
    mid_y, mid_x = MAP_HEIGHT // 2, MAP_WIDTH // 2
    assert hm[mid_y, mid_x] > SEA_LEVEL


def test_export_service_validate_empty_map():
    from services.export_service import validate_before_export
    from domain.managers.state import StateManager
    from domain.managers.country import CountryManager

    class _FakeCanvas:
        province_map = np.zeros((10, 10), dtype=np.int32)

    warnings = validate_before_export(_FakeCanvas(), StateManager(), CountryManager())
    assert any("province" in w.lower() for w in warnings)


def test_export_service_validate_empty_map_in_english():
    from services.export_service import validate_before_export
    from domain.managers.state import StateManager
    from domain.managers.country import CountryManager
    from ui.i18n import set_language

    class _FakeCanvas:
        province_map = np.zeros((10, 10), dtype=np.int32)

    set_language("en")
    warnings = validate_before_export(_FakeCanvas(), StateManager(), CountryManager())
    assert warnings == ["No province data; generate provinces first"]


def test_export_service_validate_missing_owner():
    from services.export_service import validate_before_export
    from domain.managers.state import StateManager, StateData
    from domain.managers.country import CountryManager

    class _FakeCanvas:
        province_map = np.ones((10, 10), dtype=np.int32)

    state_mgr = StateManager()
    state_mgr._states[1] = StateData(id=1, provinces=[1])
    country_mgr = CountryManager()
    country_mgr.create_country("TST", "Test", (100, 100, 100))
    country_mgr.set_capital("TST", 1)

    warnings = validate_before_export(_FakeCanvas(), state_mgr, country_mgr)
    # Should warn that State 1 has no country owner.
    assert any("no country" in w.lower() for w in warnings)


def test_export_service_validate_river_issues():
    """The river lacks source → pre-clearance warning; the river is legal → no river warning."""
    from services.export_service import validate_before_export
    from domain.managers.state import StateManager
    from domain.managers.country import CountryManager

    class _FakeCanvas:
        province_map = np.ones((10, 10), dtype=np.int32)
        river_map = np.full((10, 10), 255, dtype=np.uint8)

    canvas = _FakeCanvas()
    canvas.river_map[5, 2:8] = 3  # A section of river without source markers

    warnings = validate_before_export(canvas, StateManager(), CountryManager())
    assert any("river" in w.lower() and "source" in w.lower() for w in warnings)

    canvas.river_map[5, 2] = 0  # Make up for the source
    warnings = validate_before_export(canvas, StateManager(), CountryManager())
    assert not any(
        w.startswith("River:") and "validation passed" not in w.lower()
        for w in warnings
    )


# ────────── state ↔ strategic area alignment (pre_export_check_and_fix 5.4/5.6) ──────────

def _make_align_fixture(province_map, tile_map, state_provs, region_provs):
    """Construct three managers of state/country/strategic_region."""
    from domain.managers.state import StateManager
    from domain.managers.country import CountryManager
    from domain.managers.strategic_region import StrategicRegionManager

    state_mgr = StateManager()
    for provs in state_provs:
        state_mgr.create_state(list(provs))
    country_mgr = CountryManager()
    country_mgr.create_country("AAA", "Test", (100, 100, 100))
    sr_mgr = StrategicRegionManager()
    for provs in region_provs:
        r = sr_mgr.create_region()
        r.province_ids = list(provs)
    return state_mgr, country_mgr, sr_mgr


def test_pre_export_aligns_split_state_to_one_region():
    """The connected state is divided by two strategic areas → automatically merged into the same strategic area."""
    from services.export_service import pre_export_check_and_fix
    from data.constants import TILE_LAND

    # Province 1 (left half) + Province 2 (right half), all land, both belong to state 1
    pm = np.ones((6, 6), dtype=np.int32)
    pm[:, 3:] = 2
    tm = np.full((6, 6), TILE_LAND, dtype=np.uint8)
    state_mgr, country_mgr, sr_mgr = _make_align_fixture(
        pm, tm, state_provs=[[1, 2]], region_provs=[[1], [2]])

    report = pre_export_check_and_fix(tm, pm, None, state_mgr, country_mgr,
                                      strategic_region_mgr=sr_mgr)

    r1 = sr_mgr.get_region_of_province(1)
    r2 = sr_mgr.get_region_of_province(2)
    assert r1 == r2 and r1 != 0
    assert sr_mgr.count() == 1  # The vacated strategic area has been deleted
    assert any("strategic-region" in f for f in report.fixed)
    assert not any("exclave" in w for w in report.warnings)


def test_pre_export_enclave_state_warns():
    """The state itself is not connected (two blocks across the sea) → cannot be merged, only a warning is issued and the data is not moved."""
    from services.export_service import pre_export_check_and_fix
    from data.constants import TILE_LAND, TILE_SEA

    # Province 1 (left island) | Province 3 (sea) | Province 2 (right island), state 1 = [1, 2]
    pm = np.ones((5, 7), dtype=np.int32)
    pm[:, 2:5] = 3
    pm[:, 5:] = 2
    tm = np.full((5, 7), TILE_LAND, dtype=np.uint8)
    tm[:, 2:5] = TILE_SEA
    state_mgr, country_mgr, sr_mgr = _make_align_fixture(
        pm, tm, state_provs=[[1, 2]], region_provs=[[1], [2], [3]])

    report = pre_export_check_and_fix(tm, pm, None, state_mgr, country_mgr,
                                      strategic_region_mgr=sr_mgr)

    # Each of the two pieces of land should keep its original area and cannot be forcibly pulled together (it will create disconnected strategic areas)
    assert sr_mgr.get_region_of_province(1) != sr_mgr.get_region_of_province(2)
    assert any("exclave" in w for w in report.warnings)


def test_pre_export_pulls_unassigned_province_into_state_region():
    """There are provinces in the state but no strategic areas are allocated → Follow other provinces in the state to enter the same strategic area."""
    from services.export_service import pre_export_check_and_fix
    from data.constants import TILE_LAND

    pm = np.ones((6, 6), dtype=np.int32)
    pm[:, 3:] = 2
    tm = np.full((6, 6), TILE_LAND, dtype=np.uint8)
    # Province 2 has no strategic areas assigned to it
    state_mgr, country_mgr, sr_mgr = _make_align_fixture(
        pm, tm, state_provs=[[1, 2]], region_provs=[[1]])

    report = pre_export_check_and_fix(tm, pm, None, state_mgr, country_mgr,
                                      strategic_region_mgr=sr_mgr)

    rid = sr_mgr.get_region_of_province(1)
    assert sr_mgr.get_region_of_province(2) == rid and rid != 0
    assert not any("exclave" in w for w in report.warnings)
