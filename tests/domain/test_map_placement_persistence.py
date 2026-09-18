"""M5 slice: map placement lifecycle and persistence."""
from __future__ import annotations
import types
import numpy as np
import pytest
import data.constants as _constants
from data.constants import set_map_size
from domain.managers.map_placement import MapPlacementManager
from domain.managers.state import StateManager
from domain.managers.country import CountryManager
pytestmark = pytest.mark.unit
@pytest.fixture(autouse=True)
def _restore_map_size():
    w, h = _constants.MAP_WIDTH, _constants.MAP_HEIGHT
    yield
    set_map_size(w, h)
def _populated_mgr():
    mgr = MapPlacementManager()
    mgr.set_province_slot(5, 2, 1.5, 2.25, rotation=45.5, height=3.125, meaning="city", provenance="imported")
    mgr.set_province_slot(3, 0, 0.125, 0.375, provenance="generated")
    mgr.mark_slot_reviewed(3, 0, "reviewed", allow_auto=True)
    bid = mgr.add_building(5, "bunker", 10.75, 20.5, rotation=90.0, height=1.5, state_id=1, provenance="authored")
    fbid = mgr.add_building(3, "arms_factory", 4.125, 6.875, provenance="fallback")
    mgr.mark_building_reviewed(fbid, "accepted", allow_auto=True)
    mgr.set_port(7, 3.5, 4.5, rotation=12.25, height=0.75, sea_province=9, provenance="authored")
    gport_prov = 11
    mgr.set_port(gport_prov, 1.125, 2.125, provenance="generated")
    mgr.mark_port_reviewed(gport_prov, "reviewed", allow_auto=True)
    wid = mgr.add_weather(2, 100.125, 200.5, size="small", kind="winter", provenance="authored")
    gwid = mgr.add_weather(1, 1.5, 2.25, provenance="fallback")
    mgr.mark_weather_reviewed(gwid, "reviewed", allow_auto=True)
    return mgr
def _workspace_tmp_path(name):
    import os as _os
    from pathlib import Path as _Path
    base = _Path('tmp') / 'm5-placement-tmp'
    base.mkdir(parents=True, exist_ok=True)
    return str(base / name)
def _small_arrays():
    tm = np.ones((2, 2), dtype=np.uint8)
    pm = np.ones((2, 2), dtype=np.int32)
    ter = np.zeros((2, 2), dtype=np.uint8)
    hm = np.full((2, 2), 40, dtype=np.uint8)
    return tm, pm, ter, hm
def test_archive_round_trip_preserves_floats_and_provenance():
    from domain.project_io import save_project, load_project
    mgr = _populated_mgr()
    expected = mgr.to_dict()
    states, countries = StateManager(), CountryManager()
    tm, pm, ter, hm = _small_arrays()
    path = _workspace_tmp_path("placement.hoi4proj")
    save_project(str(path), tile_map=tm, province_map=pm, terrain_map=ter, height_map=hm, state_mgr=states, country_mgr=countries, map_placement_mgr=mgr)
    import zipfile
    with zipfile.ZipFile(str(path)) as _zf:
        assert "placements.json" in _zf.namelist()
    fresh = MapPlacementManager()
    rs, rc = StateManager(), CountryManager()
    load_project(str(path), rs, rc, map_placement_mgr=fresh)
    assert fresh.to_dict() == expected
    slot = fresh.get_province_slot(5, 2)
    assert slot.x == 1.5 and slot.y == 2.25 and slot.rotation == 45.5 and slot.height == 3.125
    assert slot.provenance == "imported" and slot.review_status == "unreviewed"
    gslot = fresh.get_province_slot(3, 0)
    assert gslot.x == 0.125 and gslot.provenance == "generated" and gslot.review_status == "reviewed"
    b = [r for r in fresh.list_buildings() if r.building_type == "bunker"][0]
    assert b.x == 10.75 and b.y == 20.5 and b.provenance == "authored"
    fb = [r for r in fresh.list_buildings() if r.building_type == "arms_factory"][0]
    assert fb.x == 4.125 and fb.provenance == "fallback" and fb.review_status == "accepted"
    port = fresh.get_port(7)
    assert port.x == 3.5 and port.sea_province == 9 and port.rotation == 12.25
    gport = fresh.get_port(11)
    assert gport.provenance == "generated" and gport.review_status == "reviewed"
def test_old_archive_without_placements_clears_manager():
    from domain.project_io import save_project, load_project
    states, countries = StateManager(), CountryManager()
    tm, pm, ter, hm = _small_arrays()
    path = _workspace_tmp_path("old.hoi4proj")
    save_project(str(path), tile_map=tm, province_map=pm, terrain_map=ter, height_map=hm, state_mgr=states, country_mgr=countries)
    import zipfile
    with zipfile.ZipFile(str(path)) as _zf:
        assert "placements.json" not in _zf.namelist()
    mgr = _populated_mgr()
    assert mgr.count() > 0
    rs, rc = StateManager(), CountryManager()
    load_project(str(path), rs, rc, map_placement_mgr=mgr)
    assert mgr.count() == 0
    assert mgr.to_dict()["province_slots"] == []
def test_project_init_and_new_reset_manager():
    from model.project import Project
    proj = Project()
    assert hasattr(proj, "map_placement_mgr")
    assert proj.map_placement_mgr.count() == 0
    proj.map_placement_mgr.set_province_slot(1, 0, 1.5, 2.5)
    assert proj.map_placement_mgr.count() == 1
    proj.new_project(8, 4)
    assert proj.map_placement_mgr.count() == 0
def test_project_save_load_passes_manager():
    from model.project import Project
    proj = Project()
    proj.new_project(8, 4)
    proj.map_placement_mgr.set_province_slot(2, 1, 1.5, 2.25, rotation=7.75, provenance="generated")
    proj.map_placement_mgr.mark_slot_reviewed(2, 1, "accepted", allow_auto=True)
    bid = proj.map_placement_mgr.add_building(2, "bunker", 10.125, 20.375, provenance="fallback")
    proj.map_placement_mgr.mark_building_reviewed(bid, "reviewed", allow_auto=True)
    expected = proj.map_placement_mgr.to_dict()
    path = _workspace_tmp_path("proj.hoi4proj")
    proj.save(path)
    proj2 = Project()
    proj2.load(path)
    assert proj2.map_placement_mgr.to_dict() == expected
    slot = proj2.map_placement_mgr.get_province_slot(2, 1)
    assert slot.x == 1.5 and slot.provenance == "generated" and slot.review_status == "accepted"
def test_service_save_load_forwards_manager():
    from services.project_service import save_project as svc_save, load_project as svc_load
    mgr = _populated_mgr()
    expected = mgr.to_dict()
    tm, pm, ter, hm = _small_arrays()
    canvas = types.SimpleNamespace(tile_map=tm, province_map=pm, terrain_map=ter, height_map=hm, river_map=None, map_data=types.SimpleNamespace(provincial_terrain={}, tile_snapshot=None))
    states, countries = StateManager(), CountryManager()
    path = _workspace_tmp_path("svc.hoi4proj")
    svc_save(str(path), canvas, states, countries, None, map_placement_mgr=mgr)
    fresh_mgr = MapPlacementManager()
    canvas2 = types.SimpleNamespace(tile_map=None, province_map=None, terrain_map=None, height_map=None, river_map=np.zeros((2, 2), dtype=np.uint8), map_data=types.SimpleNamespace(provincial_terrain={}, tile_snapshot=None))
    rs, rc = StateManager(), CountryManager()
    svc_load(str(path), canvas2, rs, rc, None, map_placement_mgr=fresh_mgr)
    assert fresh_mgr.to_dict() == expected
def test_compact_remaps_provinces_and_drops_dead():
    from domain.map_data import MapData
    set_map_size(8, 4)
    md = MapData()
    md.province_map = np.array([[0, 0, 1, 1, 3, 3, 5, 5],[0, 0, 1, 1, 3, 3, 5, 5],[0, 0, 1, 1, 3, 3, 5, 5],[0, 0, 1, 1, 3, 3, 5, 5]], dtype=np.int32)
    md.tile_map = np.ones((4, 8), dtype=np.uint8)
    mgr = MapPlacementManager()
    mgr.set_province_slot(1, 0, 1.5, 1.5)
    mgr.set_province_slot(3, 1, 2.5, 2.5)
    mgr.set_province_slot(5, 2, 3.125, 4.125)
    b_keep = mgr.add_building(3, "bunker", 10.75, 20.5, state_id=1)
    b_dead = mgr.add_building(4, "arms_factory", 1.0, 1.0)
    mgr.set_port(5, 5.5, 6.5, sea_province=3)
    mgr.set_port(1, 1.25, 1.75, sea_province=4)
    mapping = md.compact_with_references(map_placement_mgr=mgr)
    assert mapping.get(1) == 1 and mapping.get(3) == 2 and mapping.get(5) == 3
    assert mgr.get_province_slot(1, 0) is not None
    assert mgr.get_province_slot(2, 1) is not None
    assert mgr.get_province_slot(3, 2) is not None
    assert mgr.get_province_slot(3, 2).x == 3.125
    assert mgr.get_building(b_keep) is not None and mgr.get_building(b_keep).province_id == 2
    assert mgr.get_building(b_dead) is None
    kept_port = mgr.get_port(3)
    assert kept_port is not None and kept_port.sea_province == 2 and kept_port.x == 5.5
    sea_cleared = mgr.get_port(1)
    assert sea_cleared is not None and sea_cleared.sea_province is None
    assert mgr.get_port(4) is None
