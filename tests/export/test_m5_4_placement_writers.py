"""M5.4 profile aware placement writers."""
from __future__ import annotations
import inspect
import numpy as np
import pytest
from data.constants import TILE_LAND, TILE_SEA
from domain.managers.map_placement import MapPlacementManager
pytestmark = pytest.mark.unit
def _small_maps():
    province_map = np.array([[1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    tile_map = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    return province_map, tile_map
def _complete_slots(mgr, pid, base_x=10.0, base_y=1.5, review="reviewed"):
    for slot in range(6):
        mgr.set_province_slot(pid, slot, base_x + float(slot) * 0.25, base_y + float(slot) * 0.1, rotation=2.5 + float(slot), height=7.25 + float(slot) * 0.5, provenance="authored", review_status=review)
def test_foundation_positions_requires_complete_reviewed_slots(tmp_path):
    from export.writers.map.positions import write_positions_txt
    province_map, tile_map = _small_maps()
    mgr = MapPlacementManager()
    _complete_slots(mgr, 1, base_x=1.25, base_y=0.5, review="reviewed")
    for slot in range(3):
        mgr.set_province_slot(2, slot, 2.5 + float(slot), 1.5, provenance="authored", review_status="reviewed")
    write_positions_txt(province_map, tile_map, str(tmp_path), placement_manager=mgr, profile_name="foundation")
    text = (tmp_path / "map" / "positions.txt").read_text(encoding="utf-8")
    assert "1={" in text
    assert "2={" not in text
    assert "0.000 0.000" not in text
    lines = [l for l in text.splitlines() if "1.250" in l or "1.500" in l]
    assert len(lines) > 0
def test_foundation_positions_preserves_floats_and_bottom_origin(tmp_path):
    from export.writers.map.positions import write_positions_txt
    province_map, tile_map = _small_maps()
    mgr = MapPlacementManager()
    mgr.set_province_slot(1, 0, 1.25, 0.5, rotation=2.5, height=7.25, provenance="authored", review_status="reviewed")
    mgr.set_province_slot(1, 1, 1.5, 0.6, rotation=3.5, height=7.75, provenance="authored", review_status="accepted")
    mgr.set_province_slot(1, 2, 1.75, 0.7, rotation=4.5, height=8.25, provenance="authored", review_status="reviewed")
    mgr.set_province_slot(1, 3, 2.0, 0.8, rotation=5.5, height=8.75, provenance="authored", review_status="reviewed")
    mgr.set_province_slot(1, 4, 2.25, 0.9, rotation=6.5, height=9.25, provenance="authored", review_status="reviewed")
    mgr.set_province_slot(1, 5, 2.5, 1.0, rotation=7.5, height=9.75, provenance="authored", review_status="reviewed")
    write_positions_txt(province_map, tile_map, str(tmp_path), placement_manager=mgr, profile_name="foundation")
    text = (tmp_path / "map" / "positions.txt").read_text(encoding="utf-8")
    assert "1.250 9.500 3.500" in text
    assert "2.500" in text
    assert "2.500" in text
    assert "7.250" in text
    assert "7.750" in text
    assert text.count("1.250 9.500 3.500") == 1
def test_foundation_buildings_omits_placeholders_and_unreviewed(tmp_path):
    from export.writers.map.buildings import write_buildings
    province_map, tile_map = _small_maps()
    states = {1: [1, 2]}
    mgr = MapPlacementManager()
    mgr.add_building(1, "bunker", 1.5, 0.5, rotation=1.0, height=2.0, state_id=1, provenance="authored", review_status="reviewed")
    mgr.add_building(1, "arms_factory", 2.5, 0.5, state_id=1, provenance="authored", review_status="unreviewed")
    mgr.add_building(2, "industrial_complex", 2.5, 1.5, state_id=1, provenance="generated", review_status="unreviewed")
    write_buildings(states, province_map, tile_map, str(tmp_path), land_to_sea={}, placement_manager=mgr, profile_name="foundation")
    lines = (tmp_path / "map" / "buildings.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "bunker" in lines[0]
    assert "1.50" in lines[0]
    assert "arms_factory" not in "\n".join(lines)
    assert "industrial_complex" not in "\n".join(lines)
def test_foundation_buildings_accepts_reviewed_generated(tmp_path):
    from export.writers.map.buildings import write_buildings
    province_map, tile_map = _small_maps()
    states = {1: [1]}
    mgr = MapPlacementManager()
    bid = mgr.add_building(1, "fuel_silo", 1.5, 0.5, state_id=1, provenance="generated", review_status="unreviewed")
    mgr.mark_building_reviewed(bid, "reviewed", allow_auto=True)
    write_buildings(states, province_map, tile_map, str(tmp_path), land_to_sea={}, placement_manager=mgr, profile_name="foundation")
    text = (tmp_path / "map" / "buildings.txt").read_text(encoding="utf-8")
    assert "fuel_silo" in text
    assert "1.50" in text
def test_foundation_ports_use_exact_sea_and_omit_unreviewed(tmp_path):
    from export.writers.map.buildings import write_buildings
    province_map = np.array([[1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    tile_map = np.array([[TILE_LAND, TILE_LAND, TILE_SEA, TILE_SEA], [TILE_LAND, TILE_LAND, TILE_SEA, TILE_SEA]], dtype=np.uint8)
    states = {1: [1]}
    mgr = MapPlacementManager()
    mgr.set_port(1, 1.5, 0.5, rotation=4.0, height=5.0, sea_province=2, provenance="authored", review_status="reviewed")
    write_buildings(states, province_map, tile_map, str(tmp_path), land_to_sea={1: 99}, placement_manager=mgr, profile_name="foundation")
    text = (tmp_path / "map" / "buildings.txt").read_text(encoding="utf-8")
    assert "naval_base_spawn" in text
    assert ";2" in text
    assert ";99" not in text
    assert "4.00" in text
    assert "5.00" in text
def test_scaffold_and_legacy_keep_placeholders_with_generated_marker(tmp_path):
    from export.writers.map.buildings import write_buildings
    from export.writers.map.positions import write_positions_txt
    province_map, tile_map = _small_maps()
    states = {1: [1, 2]}
    mgr = MapPlacementManager()
    _complete_slots(mgr, 1, base_x=1.25, base_y=0.5, review="reviewed")
    mgr.add_building(1, "bunker", 1.5, 0.5, state_id=1, provenance="authored", review_status="reviewed")
    for profile in ("scaffold", "legacy_full"):
        out = tmp_path / profile
        write_buildings(states, province_map, tile_map, str(out), land_to_sea={}, placement_manager=mgr, profile_name=profile)
        btext = (out / "map" / "buildings.txt").read_text(encoding="utf-8")
        assert "generated" in btext.lower()
        assert "arms_factory" in btext
        assert "bunker" in btext
        write_positions_txt(province_map, tile_map, str(out), placement_manager=mgr, profile_name=profile)
        ptext = (out / "map" / "positions.txt").read_text(encoding="utf-8")
        assert "generated" in ptext.lower()
        assert "1={" in ptext
        assert "2={" in ptext
def test_legacy_direct_calls_preserve_positional_compatibility(tmp_path):
    from export.writers.map.buildings import write_buildings
    from export.writers.map.positions import write_positions_txt
    import inspect
    sig_b = inspect.signature(write_buildings)
    names_b = list(sig_b.parameters.keys())
    assert names_b[:9] == ["states", "province_map", "tile_map", "output_dir", "sea_ids", "land_to_sea", "pid_count", "sum_x", "sum_y"]
    for pname in ("placement_manager", "map_placement_mgr", "profile_name"):
        assert pname in names_b
        assert sig_b.parameters[pname].default is None
    sig_p = inspect.signature(write_positions_txt)
    names_p = list(sig_p.parameters.keys())
    assert names_p[:6] == ["province_map", "tile_map", "output_dir", "pid_count", "sum_x", "sum_y"]
    tile_map = np.array([[TILE_SEA, TILE_LAND], [TILE_SEA, TILE_LAND]], dtype=np.uint8)
    province_map = np.array([[2, 1], [2, 1]], dtype=np.int32)
    write_buildings({1: [1]}, province_map, tile_map, str(tmp_path), land_to_sea={1: 2})
    lines = (tmp_path / "map" / "buildings.txt").read_text(encoding="utf-8").splitlines()
    assert "1;naval_base_spawn;1.50;11.00;1.50;0.00;2" in lines
    assert not any(l.startswith("#") for l in lines)
    out2 = tmp_path / "pos"
    write_positions_txt(province_map, tile_map, str(out2))
    ptext = (out2 / "map" / "positions.txt").read_text(encoding="utf-8")
    assert "1={" in ptext
    assert "generated" not in ptext.lower()
def test_stage_passes_manager_and_profile(tmp_path):
    from export.stages.base import StageContext
    from export.stages import placements
    import numpy as np
    province_map = np.array([[1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    tile_map = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    mgr = MapPlacementManager()
    _complete_slots(mgr, 1, base_x=1.25, base_y=0.5, review="reviewed")
    mgr.add_building(1, "bunker", 1.5, 0.5, state_id=5, provenance="authored", review_status="reviewed")
    ctx = StageContext(profile_name="foundation", output_dir=str(tmp_path / "found"), province_map=province_map, tile_map=tile_map, map_placement_mgr=mgr, scratch={"states": {5: [1, 2]}, "sea_ids": [], "land_to_sea": {}, "pid_count": None, "sum_x": None, "sum_y": None, "coastal_set": set(), "land_ids": [1, 2], "sea_ids": []})
    result = placements.run(ctx)
    assert any("foundation" in n.lower() for n in result.notes)
    ptext = (tmp_path / "found" / "map" / "positions.txt").read_text(encoding="utf-8")
    assert "1={" in ptext
    assert "2={" not in ptext
    btext = (tmp_path / "found" / "map" / "buildings.txt").read_text(encoding="utf-8")
    assert "bunker" in btext
    assert "arms_factory" not in btext
    ctx2 = StageContext(profile_name="scaffold", output_dir=str(tmp_path / "scaf"), province_map=province_map, tile_map=tile_map, map_placement_mgr=mgr, scratch={"states": {5: [1, 2]}, "sea_ids": [], "land_to_sea": {}, "pid_count": None, "sum_x": None, "sum_y": None, "coastal_set": set(), "land_ids": [1, 2], "sea_ids": []})
    result2 = placements.run(ctx2)
    assert any("generated" in n.lower() for n in result2.notes)
    btext2 = (tmp_path / "scaf" / "map" / "buildings.txt").read_text(encoding="utf-8")
    assert "generated" in btext2.lower()
