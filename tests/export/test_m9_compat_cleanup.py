"""M9.1/M9.2 compatibility facade and duplication-cleanup regressions."""
from __future__ import annotations

import shutil
import uuid
import warnings
from pathlib import Path

import numpy as np
import pytest

from data.constants import REPLACE_PATHS, TILE_LAND, TILE_SEA

pytestmark = pytest.mark.unit


def _local_tmp(request, subdir):
    root = Path("tmp/m9-test-tmp") / ("%s-%s-%s" % (request.node.name[:40], subdir, uuid.uuid4().hex[:8]))
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def m9_tmp(request):
    root = _local_tmp(request, "root")
    import data.constants as constants
    try:
        yield root
    finally:
        # The compatibility facade refreshes the process-wide writer size for
        # its tiny synthetic map. Restore the repository default so later Qt
        # canvas tests do not combine an 8x8 MapData with a 5632x2048 buffer.
        constants.set_map_size(5632, 2048)
        shutil.rmtree(root, ignore_errors=True)


def _tiny_maps():
    tile = np.full((8, 8), TILE_SEA, dtype=np.uint8)
    tile[1:7, 1:7] = TILE_LAND
    prov = np.zeros((8, 8), dtype=np.int32)
    prov[1:7, 1:4] = 1
    prov[1:7, 4:7] = 2
    terrain = np.zeros((8, 8), dtype=np.uint8)
    height = np.full((8, 8), 100, dtype=np.uint8)
    return tile, prov, terrain, height


def test_translate_legacy_scope_resolves_legacy_full():
    from domain.export_contract import translate_legacy_scope
    profile, normalized = translate_legacy_scope({"map": True, "supply": False})
    assert profile == "legacy_full"
    assert normalized == {"map": True, "supply": False}
    profile2, normalized2 = translate_legacy_scope(None)
    assert profile2 == "legacy_full"
    assert normalized2 == {}


def test_translate_legacy_scope_rejects_unknown_keys():
    from domain.export_contract import PlanRejected, translate_legacy_scope
    with pytest.raises(PlanRejected):
        translate_legacy_scope({"nonexistent_layer": True})


def test_translate_legacy_scope_does_not_mutate_caller():
    from domain.export_contract import translate_legacy_scope
    scope = {"map": True}
    translate_legacy_scope(scope)
    assert scope == {"map": True}


def test_plan_export_scope_warns_and_keeps_legacy_profile():
    from services.export_planner import plan_export

    tile, prov, terrain, height = _tiny_maps()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        plan = plan_export(
            tile,
            prov,
            terrain_map=terrain,
            height_map=height,
            scope={"map": True, "supply": False},
        )
    assert plan.profile_name == "legacy_full"
    assert plan.scope == {"map": True, "supply": False}
    assert any(
        issubclass(item.category, DeprecationWarning)
        and "plan_export(scope=...)" in str(item.message)
        for item in caught
    )


def test_export_full_mod_scope_warns_but_keeps_output(m9_tmp):
    from export.mod_exporter import export_full_mod
    tile, prov, terrain, height = _tiny_maps()
    out_plain = m9_tmp / "plain"
    export_full_mod(tile.copy(), prov.copy(), str(out_plain), terrain_map=terrain.copy(), height_map=height.copy())
    out_scoped = m9_tmp / "scoped"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        export_full_mod(
            tile.copy(), prov.copy(), str(out_scoped),
            terrain_map=terrain.copy(), height_map=height.copy(),
            scope={"map": True, "supply": True},
        )
    assert any(issubclass(w.category, DeprecationWarning) and "legacy_full" in str(w.message) for w in caught)
    for rel in ("map/definition.csv", "map/provinces.bmp", "map/terrain.bmp"):
        assert (out_scoped / rel).is_file()
        assert (out_scoped / rel).stat().st_size > 0


def test_export_full_mod_unknown_scope_key_raises(m9_tmp):
    from export.mod_exporter import export_full_mod
    from domain.export_contract import PlanRejected
    tile, prov, terrain, height = _tiny_maps()
    with pytest.raises(PlanRejected):
        export_full_mod(
            tile.copy(), prov.copy(), str(m9_tmp / "bad"),
            terrain_map=terrain.copy(), height_map=height.copy(),
            scope={"bogus_layer": True},
        )


def test_old_archive_without_meta_loads(m9_tmp):
    import json
    from io import BytesIO
    from zipfile import ZipFile, ZIP_DEFLATED
    from domain.managers.state import StateManager
    from domain.managers.country import CountryManager
    from domain.project_io import load_project
    tile, prov, terrain, height = _tiny_maps()
    archive = m9_tmp / "legacy.hoi4proj"
    states = StateManager()
    sid = states.create_state("S1")
    sid.provinces = [1]
    countries = CountryManager()
    countries.create_country("AAA", "Test", (10, 20, 30))
    with ZipFile(str(archive), "w", ZIP_DEFLATED) as zf:
        for name, arr in (("tile_map.npy", tile), ("province_map.npy", prov),
                          ("terrain_map.npy", terrain), ("height_map.npy", height)):
            buf = BytesIO()
            np.save(buf, arr)
            zf.writestr(name, buf.getvalue())
        zf.writestr("states.json", json.dumps(
            {str(sid.id): {"id": sid.id, "name": "S1", "provinces": [1],
                           "manpower": 0, "category": "town"}}))
        zf.writestr("countries.json", json.dumps(
            {"countries": {"AAA": {"tag": "AAA", "name": "Test", "color": [10, 20, 30]}},
             "state_owners": {}}))
    states2, countries2 = StateManager(), CountryManager()
    out = load_project(str(archive), states2, countries2)
    assert out[0].shape == tile.shape
    assert states2.get_state(sid.id) is not None


def test_sidecar_without_manifest_loads_empty(m9_tmp):
    from model.project import Project
    proj_path = str(m9_tmp / "noproj.hoi4proj")
    proj = Project()
    proj._load_assets_sidecar(proj_path)
    assert proj.assets == {}
    assert proj.dirty_assets == set()


def test_csv_writer_empty_files_has_no_install_discovery(m9_tmp):
    import inspect
    from export import csv_writer
    source = inspect.getsource(csv_writer.write_empty_files)
    assert "SteamLibrary" not in source
    assert "G:/" not in source
    out = m9_tmp / "emptyfiles"
    csv_writer.write_empty_files(str(out))
    seasons = (out / "map" / "seasons.txt").read_text(encoding="utf-8")
    assert "winter" in seasons


def test_defines_legacy_floor_preserved_and_opt_out_exact(m9_tmp):
    from export.writers.common.defines import (
        LEGACY_MAX_PROVINCES_FLOOR, resolve_max_provinces, write_defines_lua,
    )
    assert LEGACY_MAX_PROVINCES_FLOOR == 25000
    assert resolve_max_provinces(10) == 110
    assert resolve_max_provinces(10, 25000) == 25000
    assert resolve_max_provinces(10, None) == 110
    assert resolve_max_provinces(30000) == 30100
    out = m9_tmp / "defines_legacy"
    write_defines_lua(str(out), province_count=10)
    assert "MAX_PROVINCES = 25000" in (out / "common" / "defines" / "01_mod_defines.lua").read_text(encoding="utf-8")
    out2 = m9_tmp / "defines_exact"
    write_defines_lua(str(out2), province_count=10, min_provinces=None)
    assert "MAX_PROVINCES = 110" in (out2 / "common" / "defines" / "01_mod_defines.lua").read_text(encoding="utf-8")


def test_staged_scaffold_chooses_non_legacy_defines_limit(m9_tmp):
    from export.stages.base import StageContext
    from export.stages import scaffold_content

    ctx = StageContext(
        profile_name="scaffold",
        output_dir=str(m9_tmp / "scaffold"),
        scope={"countries": False, "gfx": False, "localisation": False,
               "replace_path": False},
        scratch={"states": {}, "province_count": 10},
    )
    scaffold_content.run(ctx)
    defines = (m9_tmp / "scaffold" / "common" / "defines" / "01_mod_defines.lua")
    assert "MAX_PROVINCES = 110" in defines.read_text(encoding="utf-8")


def test_descriptor_policy_centralized():
    from data.constants import REPLACE_PATHS as EXPECTED
    from export.writers.map.descriptor import resolve_replace_paths
    assert resolve_replace_paths() == list(EXPECTED)
    assert resolve_replace_paths(replace_paths=["a/b"]) == ["a/b"]
    class _Profile:
        replace_paths = ["x/y"]
    assert resolve_replace_paths(profile=_Profile()) == ["x/y"]
    assert REPLACE_PATHS == list(EXPECTED)


def test_legacy_descriptor_helper_uses_central_writer(m9_tmp):
    from export import csv_writer
    from export.writers.map.descriptor import LEGACY_REPLACE_PATHS

    out = m9_tmp / "descriptor"
    csv_writer.write_descriptor_mod(str(out), mod_name="Central Policy")
    text = (out / "descriptor.mod").read_text(encoding="utf-8")
    assert 'name="Central Policy"' in text
    for path in LEGACY_REPLACE_PATHS:
        assert f'replace_path="{path}"' in text


def test_foundation_logistics_marks_fallback_as_proposal(m9_tmp):
    from export.stages.base import StageContext
    from export.stages import logistics as logistics_stage
    tile, prov, terrain, height = _tiny_maps()
    ctx = StageContext(
        profile_name="foundation", output_dir=str(m9_tmp / "found_log"),
        tile_map=tile, province_map=prov, scope={},
    )
    ctx.scratch["states"] = {1: [1], 2: [2]}
    result = logistics_stage.run(ctx)
    rail_text = (m9_tmp / "found_log" / "map" / "railways.txt").read_text(encoding="utf-8")
    supply_text = (m9_tmp / "found_log" / "map" / "supply_nodes.txt").read_text(encoding="utf-8")
    assert rail_text.strip() != ""
    assert supply_text.strip() != ""
    for line in rail_text.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            assert parts[2] != parts[3], "railway self-loop must never be emitted"
    assert any("unreviewed" in note for note in result.notes)


def test_legacy_logistics_keeps_generated_fallback(m9_tmp):
    from export.stages.base import StageContext
    from export.stages import logistics as logistics_stage
    tile, prov, terrain, height = _tiny_maps()
    ctx = StageContext(
        profile_name="legacy_full", output_dir=str(m9_tmp / "legacy_log"),
        tile_map=tile, province_map=prov, scope={},
    )
    ctx.scratch["states"] = {1: [1], 2: [2]}
    logistics_stage.run(ctx)
    rail_text = (m9_tmp / "legacy_log" / "map" / "railways.txt").read_text(encoding="utf-8")
    assert rail_text.strip() != ""


def test_export_notes_are_utf8_safe(capsys):
    from export.mod_exporter import _emit_export_note
    _emit_export_note("note with umlaut \u00e4\u00f6\u00fc and CJK \u4e2d\u6587")
    captured = capsys.readouterr()
    assert "umlaut" in captured.out


def test_no_contradictory_generation_comments():
    from pathlib import Path as _P
    text = _P("export/mod_exporter.py").read_text(encoding="utf-8")
    assert "default.map is no longer generated" not in text
    assert "adjacency_rules/ambient_object/weatherpositions/unitstacks/rocket_sites is no longer generated" not in text
