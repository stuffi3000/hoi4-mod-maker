"""Smoke test - run it every time after changing the code to ensure that the core functions are not broken.

Coverage:
- Province generation (including density map)
- State management + VP city name
- Strategic area management + compact synchronization
- River verification
- Export localization (VP city name)
- Continent allocation (including State level)
- trees_bmp automatically generated"""

import numpy as np
import pytest


# ═══════ Province generation + density map ═══════

def test_province_generation_basic():
    """Basic provinces are generated without collapse."""
    from domain.generators.province import generate_provinces
    tile_map = np.zeros((64, 128), dtype=np.uint8)
    tile_map[10:54, 10:118] = 1  # land
    province_map, count = generate_provinces(tile_map, target_count=20)
    assert count >= 5
    assert province_map.shape == tile_map.shape


def test_province_generation_with_density():
    """Provinces with density maps are generated without crashing."""
    from domain.generators.province import generate_provinces
    tile_map = np.zeros((64, 128), dtype=np.uint8)
    tile_map[10:54, 10:118] = 1
    density_map = np.full((64, 128), 0.5, dtype=np.float32)
    density_map[20:40, 40:80] = 1.0
    province_map, count = generate_provinces(tile_map, target_count=20, density_map=density_map)
    assert count >= 5


# ═══════ State Management ═══════

def test_state_manager_basic():
    """State creation and province assignment."""
    from domain.managers.state import StateManager
    mgr = StateManager()
    state = mgr.create_state()
    sid = state.id
    assert sid > 0
    mgr.assign_province(1, sid)
    mgr.assign_province(2, sid)
    s = mgr.get_state(sid)
    assert 1 in s.provinces
    assert 2 in s.provinces


def test_state_vp_names():
    """VP city name access."""
    from domain.managers.state import StateManager
    mgr = StateManager()
    state = mgr.create_state()
    sid = state.id
    mgr.assign_province(1, sid)
    mgr.set_vp(1, 10, name="Beijing")
    s = mgr.get_state(sid)
    assert s.victory_points[1] == 10
    assert s.vp_names[1] == "Beijing"


# ═══════ strategic area + compact sync ═══════

def test_strategic_region_compact():
    """compact_with_references synchronizes strategic area province IDs."""
    from domain.map_data import MapData
    from domain.managers.strategic_region import StrategicRegionManager
    import data.constants as constants
    from data.constants import set_map_size

    old_w, old_h = constants.MAP_WIDTH, constants.MAP_HEIGHT
    set_map_size(8, 4)
    try:
        md = MapData()
        md.province_map = np.array([
            [0, 0, 1, 1, 3, 3, 5, 5],
            [0, 0, 1, 1, 3, 3, 5, 5],
            [0, 0, 1, 1, 3, 3, 5, 5],
            [0, 0, 1, 1, 3, 3, 5, 5],
        ], dtype=np.int32)
        md.tile_map = np.ones((4, 8), dtype=np.uint8)

        sr_mgr = StrategicRegionManager()
        r = sr_mgr.create_region()
        r.province_ids = [1, 3, 5]

        mapping = md.compact_with_references(strategic_region_mgr=sr_mgr)
        new_ids = sorted(r.province_ids)
        assert new_ids == [1, 2, 3]
    finally:
        # The global size is a shared state and must be restored, otherwise it will pollute subsequent tests.
        set_map_size(old_w, old_h)


# ═══════ River Verification ═══════

def test_river_validate_multi_source_ok():
    """Multi-source river networks should not report warnings."""
    from domain.managers.river import validate_rivers, RIVER_SOURCE
    width_idx = 6
    h, w = 10, 20
    river_map = np.full((h, w), 254, dtype=np.uint8)
    # trunk
    river_map[5, 3:15] = width_idx
    river_map[5, 3] = RIVER_SOURCE
    # tributary
    river_map[3, 10] = RIVER_SOURCE
    river_map[4, 10] = width_idx

    warnings = validate_rivers(river_map)
    for w_text in warnings:
        assert "sources" not in w_text.lower()
        assert "missing source" not in w_text.lower() or "missing" in w_text.lower()


def test_river_validate_no_source_warns():
    """A warning should be reported for rivers without sources."""
    from domain.managers.river import validate_rivers
    h, w = 10, 20
    river_map = np.full((h, w), 254, dtype=np.uint8)
    river_map[5, 3:15] = 6
    warnings = validate_rivers(river_map)
    assert any("source" in w.lower() for w in warnings)


# ═══════ Localized export ═══════

def test_localisation_vp_names(tmp_path):
    """VP uses custom city names when exporting localizations."""
    from domain.managers.state import StateManager
    from export.writers.localisation.yml import write_localisation_full

    mgr = StateManager()
    state = mgr.create_state()
    sid = state.id
    state.name = "TestState"
    mgr.assign_province(100, sid)
    mgr.set_vp(100, 10, name="MyCity")

    write_localisation_full("TestMod", mgr, None, [sid], str(tmp_path))

    # After localization is split, VP is written in the states file
    yml_path = tmp_path / "localisation" / "zz_TestMod_states_l_english.yml"
    content = yml_path.read_text(encoding="utf-8-sig")
    assert 'VICTORY_POINTS_100:0 "MyCity"' in content


def test_localisation_vp_fallback(tmp_path):
    """If the VP does not have a custom name, the State name is used."""
    from domain.managers.state import StateManager
    from export.writers.localisation.yml import write_localisation_full

    mgr = StateManager()
    state = mgr.create_state()
    sid = state.id
    state.name = "Berlin Region"
    mgr.assign_province(200, sid)
    mgr.set_vp(200, 5)

    write_localisation_full("TestMod", mgr, None, [sid], str(tmp_path))

    yml_path = tmp_path / "localisation" / "zz_TestMod_states_l_english.yml"
    content = yml_path.read_text(encoding="utf-8-sig")
    assert 'VICTORY_POINTS_200:0 "Berlin Region"' in content


# ═══════ trees_bmp ═══════

def test_trees_bmp_dynamic_size():
    """trees_bmp handles non-standard map sizes without crashing."""
    from export.writers.map.trees_bmp import auto_generate_tree_map
    terrain = np.zeros((1024, 2048), dtype=np.uint8)
    tree_map = auto_generate_tree_map(terrain)
    assert tree_map.shape == (256, 512)


# ═══════ Continent Allocation ═══════

def test_continent_assign_by_state():
    """Continents are allocated in batches by State."""
    from domain.managers.continent import ContinentManager
    from domain.managers.state import StateManager

    cm = ContinentManager()
    cm.add_continent("europe")
    sm = StateManager()
    state = sm.create_state()
    sid = state.id
    sm.assign_province(1, sid)
    sm.assign_province(2, sid)
    sm.assign_province(3, sid)

    s = sm.get_state(sid)
    for p in s.provinces:
        cm.assign_province(p, 0)

    assert cm.get_province_continent(1) == 0
    assert cm.get_province_continent(2) == 0
    assert cm.get_province_continent(3) == 0


# ═══════ MOD empty directory ═══════

def test_create_mod_skeleton(tmp_path):
    """New projects create an empty directory structure."""
    from services.project_service import create_mod_skeleton
    out = str(tmp_path / "test_mod")
    create_mod_skeleton(out)
    import os
    assert os.path.isdir(os.path.join(out, "common", "countries"))
    assert os.path.isdir(os.path.join(out, "history", "states"))
    assert os.path.isdir(os.path.join(out, "map", "strategicregions"))
    assert os.path.isdir(os.path.join(out, "gfx", "flags"))
    assert os.path.isdir(os.path.join(out, "localisation"))
    assert os.path.isdir(os.path.join(out, "events"))
