"""M5.2 Slice 1: foundation must not silently fall back without a placement manager."""
from __future__ import annotations
import inspect
import shutil
import uuid
from pathlib import Path
import numpy as np
import pytest
from data.constants import TILE_LAND
from domain.managers.map_placement import MapPlacementManager
pytestmark = pytest.mark.unit
@pytest.fixture
def local_tmp(request, tmp_path_factory=None):
    root = Path("tmp/m5-2-test-tmp") / ("%s-%s" % (request.node.name[:40], uuid.uuid4().hex[:8]))
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)
def _small_maps():
    province_map = np.array([[1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    tile_map = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    return province_map, tile_map
def _small_plan_maps():
    province_map, tile_map = _small_maps()
    terrain_map = np.zeros((4, 4), dtype=np.uint8)
    return tile_map, province_map, terrain_map
def test_foundation_positions_refuses_without_manager():
    from export.writers.map.positions import write_positions_txt
    province_map, tile_map = _small_maps()
    with pytest.raises(ValueError, match="MapPlacementManager"):
        write_positions_txt(province_map, tile_map, "m5-2-unused-output-dir", profile_name="foundation")
    with pytest.raises(ValueError, match="[Ff]oundation"):
        write_positions_txt(province_map, tile_map, "m5-2-unused-output-dir", placement_manager=None, map_placement_mgr=None, profile_name="foundation")
def test_foundation_buildings_refuses_without_manager():
    from export.writers.map.buildings import write_buildings
    province_map, tile_map = _small_maps()
    states = {1: [1, 2]}
    with pytest.raises(ValueError, match="MapPlacementManager"):
        write_buildings(states, province_map, tile_map, "m5-2-unused-output-dir", profile_name="foundation")
    with pytest.raises(ValueError, match="[Ff]oundation"):
        write_buildings(states, province_map, tile_map, "m5-2-unused-output-dir", land_to_sea={}, placement_manager=None, map_placement_mgr=None, profile_name="foundation")
def test_foundation_weather_refuses_without_manager():
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map, _tile = _small_maps()
    region_list = [(1, [1]), (2, [2])]
    with pytest.raises(ValueError, match="MapPlacementManager"):
        write_weatherpositions(region_list, province_map, "m5-2-unused-output-dir", profile_name="foundation")
    with pytest.raises(ValueError, match="[Ff]oundation"):
        write_weatherpositions(region_list, province_map, "m5-2-unused-output-dir", map_placement_mgr=None, profile_name="foundation")
def test_legacy_omitted_profile_writers_keep_fallback(local_tmp):
    from export.writers.map.positions import write_positions_txt
    from export.writers.map.buildings import write_buildings
    from export.writers.map.strategic_regions import write_weatherpositions
    province_map, tile_map = _small_maps()
    states = {1: [1, 2]}
    out_p = local_tmp / "pos_legacy"
    write_positions_txt(province_map, tile_map, str(out_p))
    ptext = (out_p / "map" / "positions.txt").read_text(encoding="utf-8")
    assert "1={" in ptext
    assert "2={" in ptext
    out_b = local_tmp / "bld_legacy"
    write_buildings(states, province_map, tile_map, str(out_b), land_to_sea={})
    btext = (out_b / "map" / "buildings.txt").read_text(encoding="utf-8")
    assert "bunker" in btext
    assert not any(line.startswith("#") for line in btext.splitlines())
    out_w = local_tmp / "weather_legacy"
    region_list = [(1, [1]), (2, [2])]
    write_weatherpositions(region_list, province_map, str(out_w))
    wtext = (out_w / "map" / "weatherpositions.txt").read_text(encoding="utf-8")
    assert "1;" in wtext
    assert "2;" in wtext
    out_w2 = local_tmp / "weather_none"
    write_weatherpositions(region_list, province_map, str(out_w2), map_placement_mgr=None, strategic_region_mgr=None, profile_name=None)
    wtext2 = (out_w2 / "map" / "weatherpositions.txt").read_text(encoding="utf-8")
    assert wtext2 == wtext
def test_foundation_plan_blocked_when_metadata_backed_without_manager():
    from services.export_planner import plan_export
    from domain.project_meta import default_meta
    tile_map, province_map, terrain_map = _small_plan_maps()
    meta = default_meta(4, 4)
    plan = plan_export(tile_map, province_map, terrain_map, profile_name="foundation", project_meta=meta)
    assert plan.blocked
    assert any("MapPlacementManager" in blocker for blocker in plan.blockers)
    codes = [getattr(note, "code", "") for note in plan.findings]
    assert "placement.manager_missing" in codes
    blocker_notes = [note for note in plan.findings if getattr(note, "code", "") == "placement.manager_missing"]
    assert blocker_notes and all(getattr(note, "severity", "") == "blocker" for note in blocker_notes)
def test_foundation_plan_blocked_when_frozen_without_manager():
    from services.export_planner import plan_export
    tile_map, province_map, terrain_map = _small_plan_maps()
    plan = plan_export(tile_map, province_map, terrain_map, profile_name="foundation", lifecycle="frozen")
    assert plan.blocked
    assert any("MapPlacementManager" in blocker for blocker in plan.blockers)
    codes = [getattr(note, "code", "") for note in plan.findings]
    assert "placement.manager_missing" in codes
def test_legacy_direct_foundation_plan_without_meta_stays_compatible():
    from services.export_planner import plan_export
    tile_map, province_map, terrain_map = _small_plan_maps()
    plan = plan_export(tile_map, province_map, terrain_map, profile_name="foundation")
    codes = [getattr(note, "code", "") for note in plan.findings]
    assert "placement.manager_missing" not in codes
    assert not any("MapPlacementManager" in blocker for blocker in plan.blockers)
def test_legacy_foundation_plan_pipeline_keeps_compat_fallback(local_tmp):
    from services.export_planner import plan_export
    from export.stages.base import build_context_from_plan
    from export.stages import pipeline
    from domain.managers.continent import ContinentManager
    from domain.managers.country import CountryManager
    from domain.managers.state import StateManager
    tile_map, province_map, terrain_map = _small_plan_maps()
    states = StateManager()
    west = states.create_state("West")
    west.provinces = [1]
    east = states.create_state("East")
    east.provinces = [2]
    countries = CountryManager()
    country = countries.create_country("TST", "Testland", (100, 120, 200))
    countries.assign_state(west.id, "TST")
    west.owner_tag = "TST"
    countries.assign_state(east.id, "TST")
    east.owner_tag = "TST"
    country.capital = 1
    continents = ContinentManager()
    plan = plan_export(tile_map, province_map, terrain_map, state_mgr=states, country_mgr=countries, continent_mgr=continents, profile_name="foundation")
    assert not plan.blocked
    assert "placement.manager_missing" not in [getattr(note, "code", "") for note in plan.findings]
    ctx = build_context_from_plan(plan, str(local_tmp / "legacy_foundation"))
    assert ctx.profile_name == "foundation"
    assert ctx.map_placement_mgr is None
    assert ctx.scratch.get("foundation_legacy_compat") is True
    results = pipeline.run_pipeline(ctx)
    assert results
    buildings = local_tmp / "legacy_foundation" / "map" / "buildings.txt"
    positions = local_tmp / "legacy_foundation" / "map" / "positions.txt"
    weather = local_tmp / "legacy_foundation" / "map" / "weatherpositions.txt"
    assert buildings.is_file()
    assert positions.is_file()
    assert weather.is_file()
    assert "bunker" in buildings.read_text(encoding="utf-8")
    ptext = positions.read_text(encoding="utf-8")
    assert "1={" in ptext
    assert "2={" in ptext
    wtext = weather.read_text(encoding="utf-8")
    assert "1;" in wtext
    assert "2;" in wtext
def test_foundation_plan_with_manager_does_not_report_missing():
    from services.export_planner import plan_export
    from domain.project_meta import default_meta
    tile_map, province_map, terrain_map = _small_plan_maps()
    mgr = MapPlacementManager()
    meta = default_meta(4, 4)
    plan = plan_export(tile_map, province_map, terrain_map, profile_name="foundation", project_meta=meta, map_placement_mgr=mgr)
    codes = [getattr(note, "code", "") for note in plan.findings]
    assert "placement.manager_missing" not in codes
def test_writer_signatures_remain_backward_compatible():
    from export.writers.map.buildings import write_buildings
    from export.writers.map.positions import write_positions_txt
    from export.writers.map.strategic_regions import write_weatherpositions
    sig_b = inspect.signature(write_buildings)
    names_b = list(sig_b.parameters.keys())
    assert names_b[:9] == ["states", "province_map", "tile_map", "output_dir", "sea_ids", "land_to_sea", "pid_count", "sum_x", "sum_y"]
    for pname in ("placement_manager", "map_placement_mgr", "profile_name"):
        assert pname in names_b
        assert sig_b.parameters[pname].default is None
    sig_p = inspect.signature(write_positions_txt)
    names_p = list(sig_p.parameters.keys())
    assert names_p[:6] == ["province_map", "tile_map", "output_dir", "pid_count", "sum_x", "sum_y"]
    for pname in ("placement_manager", "map_placement_mgr", "profile_name"):
        assert pname in names_p
        assert sig_p.parameters[pname].default is None
    sig_w = inspect.signature(write_weatherpositions)
    names_w = list(sig_w.parameters.keys())
    assert names_w == ["region_list", "province_map", "output_dir", "map_placement_mgr", "strategic_region_mgr", "profile_name"]
    for pname in ("map_placement_mgr", "strategic_region_mgr", "profile_name"):
        assert sig_w.parameters[pname].default is None
def test_cli_planner_branch_passes_placement_manager(monkeypatch, local_tmp):
    import cli_export
    import services.export_planner as planner_module
    import services.export_service as export_service
    project = local_tmp / "proj.hoi4proj"
    project.write_bytes(b"placeholder")
    monkeypatch.setattr(cli_export, "configure_console_streams", lambda: None)
    captured_load = {}
    def fake_load(*args, **kwargs):
        captured_load.update(kwargs)
        captured_load["args"] = args
        tile_map = np.full((1024, 1024), TILE_LAND, dtype=np.uint8)
        province_map = np.zeros((1024, 1024), dtype=np.int32)
        province_map[:, :512] = 1
        province_map[:, 512:] = 2
        terrain_map = np.zeros((1024, 1024), dtype=np.uint8)
        height_map = np.zeros((1024, 1024), dtype=np.uint8)
        return (tile_map, province_map, terrain_map, height_map, None, {}, None)
    monkeypatch.setattr(cli_export, "load_project", fake_load)
    monkeypatch.setattr(cli_export, "read_project_meta", lambda *args, **kwargs: None)
    captured_plan_kwargs = {}
    real_plan_export = planner_module.plan_export
    def wrapping_plan(*args, **kwargs):
        captured_plan_kwargs.update(kwargs)
        return real_plan_export(*args, **kwargs)
    monkeypatch.setattr(planner_module, "plan_export", wrapping_plan)
    class FakeResult:
        written_files = []
        output_dir = str(local_tmp / "out")
        manifest_path = ""
    monkeypatch.setattr(export_service, "export_planned_mod", lambda *args, **kwargs: FakeResult())
    monkeypatch.setattr(cli_export, "_verify_planned_export", lambda *args, **kwargs: [])
    import types as _types
    _proj = str(project)
    _out = str(local_tmp / "out")
    args = _types.SimpleNamespace(project=_proj, output_dir=_out, profile="foundation", game_dir=None, repair="propose", manifest=None, compare_lock=None, json_report=None, overwrite=False, clean=False, backup=False, keep_staging=False, acceptance_count=0, mod_name="WorldTest")
    result = cli_export.run_planner_export(args)
    assert result == cli_export.EXIT_SUCCESS
    assert "map_placement_mgr" in captured_load
    assert isinstance(captured_load["map_placement_mgr"], MapPlacementManager)
    assert "map_placement_mgr" in captured_plan_kwargs
    assert isinstance(captured_plan_kwargs["map_placement_mgr"], MapPlacementManager)
def test_cli_legacy_branch_passes_placement_manager(monkeypatch, local_tmp):
    import cli_export
    project = local_tmp / "proj.hoi4proj"
    project.write_bytes(b"placeholder")
    monkeypatch.setattr(cli_export, "configure_console_streams", lambda: None)
    captured_load = {}
    def fake_load(*args, **kwargs):
        captured_load.update(kwargs)
        tile_map = np.ones((2, 2), dtype=np.uint8)
        province_map = np.ones((2, 2), dtype=np.int32)
        terrain_map = np.zeros((2, 2), dtype=np.uint8)
        height_map = np.array([[1, 2], [3, 4]], dtype=np.uint8)
        return (tile_map, province_map, terrain_map, height_map, None, {}, None)
    monkeypatch.setattr(cli_export, "load_project", fake_load)
    import services.export_service as export_service
    monkeypatch.setattr(export_service, "pre_export_check_and_fix", lambda *args, **kwargs: export_service.ExportReport())
    monkeypatch.setattr(export_service, "fill_default_state_data", lambda *args, **kwargs: 0)
    captured_export = {}
    def fake_export(**kwargs):
        captured_export.update(kwargs)
        out_root = Path(kwargs.get("output_dir", str(local_tmp / "output")))
        for rel in cli_export.CRITICAL_FILES:
            dest = out_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("valid\n", encoding="utf-8")
        for rel in cli_export.CRITICAL_DIRECTORIES:
            dest = out_root / rel
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "placeholder.txt").write_text("valid\n", encoding="utf-8")
        (Path(str(out_root) + ".mod")).write_text("valid\n", encoding="utf-8")
    monkeypatch.setattr(cli_export, "export_full_mod", fake_export)
    monkeypatch.setattr(cli_export, "verify_export", lambda *args, **kwargs: [])
    result = cli_export.main([str(project), str(local_tmp / "output")])
    assert result == cli_export.EXIT_SUCCESS
    assert "map_placement_mgr" in captured_load
    assert isinstance(captured_load["map_placement_mgr"], MapPlacementManager)
    assert "map_placement_mgr" in captured_export
    assert isinstance(captured_export["map_placement_mgr"], MapPlacementManager)
