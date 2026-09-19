"""M5.5 weatherpositions writer with placement support."""
from __future__ import annotations
import copy
import inspect
import numpy as np
import pytest
from domain.managers.map_placement import MapPlacementManager
from domain.managers.strategic_region import StrategicRegionManager
pytestmark = pytest.mark.unit
def _small_maps():
    province_map = np.array([[1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    return province_map
def _read_lines(out_dir):
    p = out_dir / "map" / "weatherpositions.txt"
    text = p.read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip() != ""]
    return text, lines
def test_signature_preserves_legacy_positional():
    from export.writers.map.strategic_regions import write_weatherpositions
    sig = inspect.signature(write_weatherpositions)
    names = list(sig.parameters.keys())
    assert names == ["region_list", "province_map", "output_dir", "map_placement_mgr", "strategic_region_mgr", "profile_name"]
    for pname in ("map_placement_mgr", "strategic_region_mgr", "profile_name"):
        assert sig.parameters[pname].default is None
def test_legacy_centroid_compatibility(tmp_path):
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map = _small_maps()
    region_list = [(1, [1]), (2, [2])]
    write_weatherpositions(region_list, province_map, str(tmp_path))
    text, lines = _read_lines(tmp_path)
    assert lines == ["1;0.50;10.00;2.50;small", "2;2.50;10.00;2.50;small"]
    out2 = tmp_path / "second"
    write_weatherpositions(region_list, province_map, str(out2), map_placement_mgr=None, strategic_region_mgr=None, profile_name=None)
    text2 = (out2 / "map" / "weatherpositions.txt").read_text(encoding="utf-8")
    assert text2 == text
    out3 = tmp_path / "compat_nomgr"
    write_weatherpositions(region_list, province_map, str(out3), profile_name="scaffold")
    text3 = (out3 / "map" / "weatherpositions.txt").read_text(encoding="utf-8")
    assert text3 == text
def test_foundation_filters_unreviewed_and_no_fallback(tmp_path):
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map = _small_maps()
    region_list = [(1, [1]), (2, [2])]
    mgr = MapPlacementManager()
    mgr.add_weather(1, 1.25, 0.5, height=2.0, size="small", provenance="authored", review_status="reviewed")
    mgr.add_weather(1, 1.75, 0.75, height=3.0, size="medium", provenance="authored", review_status="unreviewed")
    mgr.add_weather(2, 2.5, 1.5, height=4.0, size="large", provenance="authored", review_status="unreviewed")
    write_weatherpositions(region_list, province_map, str(tmp_path), map_placement_mgr=mgr, profile_name="foundation")
    text, lines = _read_lines(tmp_path)
    assert len(lines) == 1
    assert lines[0].startswith("1;")
    assert "1.25" in lines[0]
    assert "2;" not in text
    assert "10.00" not in text
def test_foundation_accepts_accepted_status(tmp_path):
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map = _small_maps()
    region_list = [(1, [1])]
    mgr = MapPlacementManager()
    mgr.add_weather(1, 1.5, 1.0, height=5.0, size="huge", provenance="authored", review_status="accepted")
    write_weatherpositions(region_list, province_map, str(tmp_path), map_placement_mgr=mgr, profile_name="foundation")
    text, lines = _read_lines(tmp_path)
    assert len(lines) == 1
    assert lines[0] == "1;1.50;5.00;3.00;huge"
def test_original_to_emitted_remap_with_gaps(tmp_path):
    from export.writers.map.strategic_regions import write_strategic_regions_from_mgr, write_weatherpositions
    province_map = _small_maps()
    srm = StrategicRegionManager()
    r1 = srm.create_region("R1")
    r2 = srm.create_region("R2")
    r3 = srm.create_region("R3")
    srm.assign_province(1, r1.id)
    srm.assign_province(2, r3.id)
    assert srm.get(r2.id).province_ids == []
    region_list = write_strategic_regions_from_mgr(srm, str(tmp_path))
    assert (1, [1]) in region_list
    assert any(rid == 3 for rid, _ in region_list)
    assert not any(rid == 2 for rid, _ in region_list)
    mgr = MapPlacementManager()
    mgr.add_weather(r1.id, 1.25, 0.5, height=1.0, size="small", provenance="authored", review_status="reviewed")
    mgr.add_weather(r3.id, 2.75, 1.5, height=2.0, size="medium", provenance="authored", review_status="reviewed")
    mgr.add_weather(r2.id, 9.0, 9.0, height=9.0, size="large", provenance="authored", review_status="reviewed")
    mgr.add_weather(99, 8.0, 8.0, height=8.0, size="small", provenance="authored", review_status="reviewed")
    out = tmp_path / "weather"
    write_weatherpositions(region_list, province_map, str(out), map_placement_mgr=mgr, strategic_region_mgr=srm, profile_name="foundation")
    text, lines = _read_lines(out)
    assert len(lines) == 2
    assert lines[0].startswith("1;")
    assert lines[1].startswith("3;")
    assert "1.25" in lines[0]
    assert "2.75" in lines[1]
    assert "9.00" not in text
    assert "8.00" not in text
def test_float_height_bottom_origin(tmp_path):
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map = _small_maps()
    region_list = [(1, [1])]
    mgr = MapPlacementManager()
    mgr.add_weather(1, 1.25, 0.5, height=7.25, size="small", provenance="authored", review_status="reviewed")
    write_weatherpositions(region_list, province_map, str(tmp_path), map_placement_mgr=mgr, profile_name="foundation")
    text, lines = _read_lines(tmp_path)
    assert lines == ["1;1.25;7.25;3.50;small"]
def test_multiple_positions_per_region(tmp_path):
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map = _small_maps()
    region_list = [(1, [1])]
    mgr = MapPlacementManager()
    mgr.add_weather(1, 0.25, 0.25, height=1.0, size="small", provenance="authored", review_status="reviewed")
    mgr.add_weather(1, 1.75, 2.5, height=2.0, size="large", provenance="authored", review_status="accepted")
    write_weatherpositions(region_list, province_map, str(tmp_path), map_placement_mgr=mgr, profile_name="foundation")
    text, lines = _read_lines(tmp_path)
    assert len(lines) == 2
    assert all(l.startswith("1;") for l in lines)
    assert "0.25" in lines[0]
    assert "1.75" in lines[1]
def test_valid_size_handling(tmp_path):
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map = _small_maps()
    region_list = [(1, [1])]
    for valid in ("small", "medium", "large", "huge"):
        mgr = MapPlacementManager()
        mgr.add_weather(1, 1.0, 1.0, height=1.0, size=valid, provenance="authored", review_status="reviewed")
        out = tmp_path / valid
        write_weatherpositions(region_list, province_map, str(out), map_placement_mgr=mgr, profile_name="foundation")
        _text, lines = _read_lines(out)
        assert lines[0].endswith(";" + valid)
    for bad in ("", "gigantic", "  ", "XL"):
        mgr = MapPlacementManager()
        mgr.add_weather(1, 1.0, 1.0, height=1.0, size=bad, provenance="authored", review_status="reviewed")
        out = tmp_path / ("bad_" + bad.strip().lower() if bad.strip() else "bad_blank")
        out.mkdir(parents=True, exist_ok=True)
        write_weatherpositions(region_list, province_map, str(out), map_placement_mgr=mgr, profile_name="foundation")
        _text, lines = _read_lines(out)
        assert len(lines) == 1
        tail = lines[0].rsplit(";", 1)[-1]
        assert tail in ("small", "medium", "large", "huge")
        assert tail == "small"
def test_compatibility_fallback_and_overlay(tmp_path):
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map = _small_maps()
    region_list = [(1, [1]), (2, [2])]
    mgr = MapPlacementManager()
    mgr.add_weather(1, 1.25, 0.5, height=2.5, size="medium", provenance="authored", review_status="reviewed")
    for profile in ("scaffold", "acceptance", "legacy_full"):
        out = tmp_path / profile
        write_weatherpositions(region_list, province_map, str(out), map_placement_mgr=mgr, profile_name=profile)
        text, lines = _read_lines(out)
        assert len(lines) == 2
        mgr_lines = [l for l in lines if l.startswith("1;")]
        fall_lines = [l for l in lines if l.startswith("2;")]
        assert len(mgr_lines) == 1
        assert len(fall_lines) == 1
        assert mgr_lines[0] == "1;1.25;2.50;3.50;medium"
        assert fall_lines[0] == "2;2.50;10.00;2.50;small"
def test_deterministic_output(tmp_path):
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map = _small_maps()
    region_list = [(2, [2]), (1, [1])]
    mgr = MapPlacementManager()
    mgr.add_weather(2, 2.1, 1.1, height=1.0, size="small", provenance="authored", review_status="reviewed")
    mgr.add_weather(1, 0.9, 0.4, height=1.5, size="large", provenance="authored", review_status="reviewed")
    mgr.add_weather(1, 0.5, 0.5, height=0.5, size="medium", provenance="authored", review_status="reviewed")
    out1 = tmp_path / "a"
    out2 = tmp_path / "b"
    write_weatherpositions(region_list, province_map, str(out1), map_placement_mgr=mgr, profile_name="foundation")
    write_weatherpositions(region_list, province_map, str(out2), map_placement_mgr=mgr, profile_name="foundation")
    t1 = (out1 / "map" / "weatherpositions.txt").read_text(encoding="utf-8")
    t2 = (out2 / "map" / "weatherpositions.txt").read_text(encoding="utf-8")
    assert t1 == t2
    lines = [l for l in t1.splitlines() if l.strip()]
    assert lines[0].startswith("1;")
    assert lines[1].startswith("1;")
    assert lines[2].startswith("2;")
def test_no_input_mutation(tmp_path):
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map = _small_maps()
    before_map = province_map.copy()
    region_list = [(1, [1]), (2, [2])]
    before_regions = copy.deepcopy(region_list)
    mgr = MapPlacementManager()
    mgr.add_weather(1, 1.25, 0.5, height=1.0, size="small", provenance="authored", review_status="reviewed")
    before_mgr = mgr.to_dict()
    srm = StrategicRegionManager()
    r1 = srm.create_region("A")
    r2 = srm.create_region("B")
    srm.assign_province(1, r1.id)
    srm.assign_province(2, r2.id)
    before_srm = copy.deepcopy(srm.to_dict())
    write_weatherpositions(region_list, province_map, str(tmp_path), map_placement_mgr=mgr, strategic_region_mgr=srm, profile_name="foundation")
    write_weatherpositions(region_list, province_map, str(tmp_path / "compat"), map_placement_mgr=mgr, strategic_region_mgr=srm, profile_name="scaffold")
    assert np.array_equal(province_map, before_map)
    assert region_list == before_regions
    assert mgr.to_dict() == before_mgr
    assert srm.to_dict() == before_srm


def test_regions_stage_forwards_manager_and_profile(tmp_path):
    from export.stages.base import StageContext
    from export.stages import regions
    from data.constants import TILE_LAND

    province_map = _small_maps()
    tile_map = np.full_like(province_map, TILE_LAND, dtype=np.uint8)
    srm = StrategicRegionManager()
    first = srm.create_region("first")
    second = srm.create_region("second")
    srm.assign_province(1, first.id)
    srm.assign_province(2, second.id)
    mgr = MapPlacementManager()
    mgr.add_weather(1, 0.5, 0.5, height=2.0, review_status="reviewed")
    mgr.add_weather(2, 2.5, 0.5, height=3.0, review_status="accepted")
    ctx = StageContext(
        profile_name="foundation",
        output_dir=str(tmp_path),
        province_map=province_map,
        tile_map=tile_map,
        strategic_region_mgr=srm,
        map_placement_mgr=mgr,
        scratch={"land_ids": [1, 2], "sea_ids": [], "states": {1: [1], 2: [2]}},
    )

    regions.run(ctx)

    _text, lines = _read_lines(tmp_path)
    assert lines == ["1;0.50;2.00;3.50;small", "2;2.50;3.00;3.50;small"]
