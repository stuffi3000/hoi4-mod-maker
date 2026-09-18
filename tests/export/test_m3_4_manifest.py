"""M3.4 deterministic foundation-manifest tests (first bounded slice)."""
from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.export_contract import WrittenFile
from domain.managers.continent import ContinentManager
from domain.managers.country import CountryManager
from domain.managers.state import StateManager
from services.export_manifest import (
    MANIFEST_SCHEMA,
    MANIFEST_VERSION,
    build_manifest_dict,
    canonical_manifest_dict,
    canonical_manifest_json,
    compare_with_lock,
    manifest_identity_hash,
)
from services.export_planner import plan_export
from services.game_assets import GameTarget

pytestmark = pytest.mark.unit


@pytest.fixture
def m3_4_tmp(request, tmp_path_factory):
    root = Path("tmp/m3-4-test-tmp") / ("%s-%s" % (request.node.name[:40], uuid.uuid4().hex[:8]))
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _fixture_maps(size: int = 32):
    tile = np.full((size, size), TILE_SEA, dtype=np.uint8)
    tile[4:28, 4:28] = TILE_LAND
    prov = np.zeros((size, size), dtype=np.int32)
    prov[4:28, 4:16] = 1
    prov[4:28, 16:28] = 2
    terrain = np.full((size, size), TERRAIN_PALETTE_INDEX["ocean"], dtype=np.uint8)
    terrain[4:28, 4:28] = TERRAIN_PALETTE_INDEX["plains"]
    height = np.full((size, size), 50, dtype=np.uint8)
    river = np.zeros((size, size), dtype=np.uint8)
    return tile, prov, terrain, height, river


def _fixture_managers():
    states = StateManager()
    first = states.create_state("West")
    first.provinces = [1]
    second = states.create_state("East")
    second.provinces = [2]
    countries = CountryManager()
    country = countries.create_country("TST", "Testland", (100, 120, 200))
    countries.assign_state(first.id, "TST")
    first.owner_tag = "TST"
    countries.assign_state(second.id, "TST")
    second.owner_tag = "TST"
    country.capital = 1
    return states, countries, ContinentManager()


def _base_plan(**overrides):
    tile, prov, terrain, height, river = _fixture_maps()
    states, countries, continents = _fixture_managers()
    kwargs = dict(
        tile_map=tile, province_map=prov, terrain_map=terrain,
        height_map=height, river_map=river,
        state_mgr=states, country_mgr=countries, continent_mgr=continents,
        profile_name="foundation",
    )
    kwargs.update(overrides)
    return plan_export(**kwargs)


def _fake_target(install_dir: str, validated_at: str) -> GameTarget:
    return GameTarget(
        install_dir=install_dir,
        raw_version="1.19.3.0",
        display_version="1.19.3",
        revision="0",
        checksum="abc123",
        supported_version="1.19.*",
        profile_id="hoi4-1.19",
        source="explicit",
        validated_at=validated_at,
        required_files={},
        missing_files=[],
    )


def test_schema_metadata_and_legacy_fields():
    plan = _base_plan()
    manifest = build_manifest_dict(plan, [])
    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["manifest_schema"] == MANIFEST_SCHEMA
    assert manifest["metadata"]["tool_version"]
    assert manifest["metadata"]["created_at"]
    assert manifest["metadata"]["generator"]
    assert manifest["tool_version"] == manifest["metadata"]["tool_version"]
    assert "created_at" not in manifest
    assert manifest["profile"] == "foundation"
    assert manifest["snapshot_fingerprint"] == plan.snapshot.fingerprint
    assert manifest["map_size"] == {"width": plan.snapshot.width, "height": plan.snapshot.height}
    assert "game_target" in manifest
    assert "game_profile" in manifest
    assert manifest["layers"]
    assert isinstance(manifest["scope"], dict)
    assert isinstance(manifest["counts"], dict)


def test_path_independence_install_dir_and_validated_at():
    plan = _base_plan()
    plan_a = copy.copy(plan)
    plan_b = copy.copy(plan)
    plan_a.game_target = _fake_target("C:/games/hoi4-a", "2026-01-01T00:00:00+00:00")
    plan_b.game_target = _fake_target("D:/other/hoi4-b", "2026-06-06T12:00:00+00:00")
    manifest_a = build_manifest_dict(plan_a, [])
    manifest_b = build_manifest_dict(plan_b, [])
    assert manifest_a["sources"] == manifest_b["sources"]
    assert manifest_a["target"]["identity"] == manifest_b["target"]["identity"]
    assert manifest_a["identity"]["identity_hash"] == manifest_b["identity"]["identity_hash"]
    assert manifest_a["target"]["diagnostics"]["install_dir"] != manifest_b["target"]["diagnostics"]["install_dir"]
    assert canonical_manifest_json(manifest_a) == canonical_manifest_json(manifest_b)


def test_source_hashes_present_and_sensitive():
    plan = _base_plan()
    manifest = build_manifest_dict(plan, [])
    arrays = manifest["sources"]["arrays"]
    assert set(arrays) == {"tile", "province", "terrain", "height", "river"}
    assert all(isinstance(v, str) and len(v) in (4, 64, 10) for v in arrays.values())
    managers = manifest["sources"]["managers"]
    assert "state_mgr" in managers and "country_mgr" in managers
    aux = manifest["sources"]["auxiliary"]
    for key in ("provincial_terrain", "colormap_settings", "default_map_settings", "assets", "dirty_assets"):
        assert key in aux
    base_identity = manifest["identity"]["identity_hash"]
    tile2, prov2, terrain2, height2, river2 = _fixture_maps()
    tile2 = tile2.copy()
    tile2[5, 5] = TILE_SEA
    states, countries, continents = _fixture_managers()
    changed_array = plan_export(tile2, prov2, terrain2, height_map=height2, river_map=river2, state_mgr=states, country_mgr=countries, continent_mgr=continents, profile_name="foundation")
    manifest2 = build_manifest_dict(changed_array, [])
    assert manifest2["sources"]["arrays"]["tile"] != arrays["tile"]
    assert manifest2["identity"]["identity_hash"] != base_identity
    states3, countries3, continents3 = _fixture_managers()
    extra = states3.create_state([])
    extra.provinces = [1]
    tile3, prov3, terrain3, _, _ = _fixture_maps()
    s_a, c_a, co_a = _fixture_managers()
    s_b, c_b, co_b = _fixture_managers()
    s_b.create_state([])
    plan_mgr_a = plan_export(tile3, prov3, terrain3, state_mgr=s_a, country_mgr=c_a, continent_mgr=co_a, profile_name="foundation")
    plan_mgr_b = plan_export(tile3, prov3, terrain3, state_mgr=s_b, country_mgr=c_b, continent_mgr=co_b, profile_name="foundation")
    assert build_manifest_dict(plan_mgr_a, [])["sources"]["managers"]["state_mgr"] != build_manifest_dict(plan_mgr_b, [])["sources"]["managers"]["state_mgr"]
    assert build_manifest_dict(plan_mgr_a, [])["identity"]["identity_hash"] != build_manifest_dict(plan_mgr_b, [])["identity"]["identity_hash"]
    t4, p4, te4, h4, r4 = _fixture_maps()
    sa, ca, coa = _fixture_managers()
    sb, cb, cob = _fixture_managers()
    plan_aux_a = plan_export(t4, p4, te4, state_mgr=sa, country_mgr=ca, continent_mgr=coa, profile_name="foundation", provincial_terrain={}, dirty_assets=())
    plan_aux_b = plan_export(t4, p4, te4, state_mgr=sb, country_mgr=cb, continent_mgr=cob, profile_name="foundation", provincial_terrain={1: "plains"}, dirty_assets=("map/terrain.bmp",))
    assert build_manifest_dict(plan_aux_a, [])["sources"]["auxiliary"]["provincial_terrain"] != build_manifest_dict(plan_aux_b, [])["sources"]["auxiliary"]["provincial_terrain"]
    assert build_manifest_dict(plan_aux_a, [])["sources"]["auxiliary"]["dirty_assets"] != build_manifest_dict(plan_aux_b, [])["sources"]["auxiliary"]["dirty_assets"]


def test_identity_ignores_diagnostics_and_timestamp():
    plan = _base_plan()
    plan.game_target = _fake_target("C:/games/hoi4", "2026-01-01T00:00:00+00:00")
    manifest = build_manifest_dict(plan, [])
    identity_before = manifest["identity"]["identity_hash"]
    assert "install_dir" not in json.dumps(manifest["target"]["identity"])
    assert "validated_at" not in json.dumps(manifest["target"]["identity"])
    mutated = copy.deepcopy(manifest)
    mutated["metadata"]["created_at"] = "2099-01-01T00:00:00+00:00"
    mutated["target"]["diagnostics"]["install_dir"] = "Z:/elsewhere"
    mutated["target"]["diagnostics"]["validated_at"] = "2099-12-31T23:59:59+00:00"
    assert manifest_identity_hash(mutated) == identity_before
    assert canonical_manifest_json(mutated) == canonical_manifest_json(manifest)
    portable = manifest["target"]["identity"]
    assert portable["revision"] == "0"
    assert portable["checksum"] == "abc123"
    assert portable["profile_id"] == "hoi4-1.19"


def test_deterministic_canonical_json_and_stable_ordering():
    plan_one = _base_plan()
    plan_two = _base_plan()
    manifest_one = build_manifest_dict(plan_one, [])
    manifest_two = build_manifest_dict(plan_two, [])
    assert manifest_one["identity"]["identity_hash"] == manifest_two["identity"]["identity_hash"]
    assert canonical_manifest_json(manifest_one) == canonical_manifest_json(manifest_two)
    canon = canonical_manifest_dict(manifest_one)
    assert "metadata" not in canon
    assert "created_at" not in canon
    assert "tool_version" not in canon
    assert "diagnostics" not in canon.get("target", {})
    files_a = [WrittenFile("b.txt", 2, "h2"), WrittenFile("a.txt", 1, "h1")]
    files_b = [WrittenFile("a.txt", 1, "h1"), WrittenFile("b.txt", 2, "h2")]
    manifest_a = build_manifest_dict(plan_one, files_a)
    manifest_b = build_manifest_dict(plan_one, files_b)
    assert [w["rel_path"] for w in manifest_a["written_files"]] == ["a.txt", "b.txt"]
    assert manifest_a["written_files"] == manifest_b["written_files"]
    assert canonical_manifest_json(manifest_a) == canonical_manifest_json(manifest_b)
    raw = json.dumps(manifest_one, sort_keys=True)
    assert json.loads(raw)["identity"]["identity_hash"] == manifest_one["identity"]["identity_hash"]


def test_counts_scope_layers_and_legacy():
    plan = _base_plan()
    plan.scope = {"map": True, "states": True}
    manifest = build_manifest_dict(plan, [])
    assert manifest["counts"]["province_ids"] == 2
    assert manifest["counts"]["province_max"] == 2
    assert manifest["counts"]["managers"]["state_mgr"] == 2
    assert manifest["counts"]["managers"]["country_mgr"] == 1
    assert manifest["scope"] == {"map": True, "states": True}
    assert manifest["layers"] == list(plan.layers)
    assert manifest["project"]["profile_id"] == plan.snapshot.profile_id
    assert manifest["game_profile"] is not None
    assert manifest["snapshot_fingerprint"]
    assert manifest["map_size"]["width"] == plan.snapshot.width
    profile_changed = _base_plan(profile_name="scaffold")
    assert build_manifest_dict(profile_changed, [])["identity"]["identity_hash"] != manifest["identity"]["identity_hash"]


def test_does_not_mutate_snapshot_or_managers():
    plan = _base_plan()
    snap = plan.snapshot
    fp_before = snap.fingerprint
    tile_before = snap.tile_map.tobytes()
    prov_before = snap.province_map.tobytes()
    mgr_before = snap.managers_dict()["state_mgr"].states.keys()
    mgr_keys_before = sorted(mgr_before)
    build_manifest_dict(plan, [WrittenFile("a.txt", 1, "h")])
    assert snap.fingerprint == fp_before
    assert snap.tile_map.tobytes() == tile_before
    assert snap.province_map.tobytes() == prov_before
    assert sorted(snap.managers_dict()["state_mgr"].states.keys()) == mgr_keys_before


def test_legacy_lock_comparison_still_works(m3_4_tmp):
    from services.export_manifest import write_lock_file
    plan = _base_plan()
    manifest = build_manifest_dict(plan, [])
    lock_path = write_lock_file(str(m3_4_tmp), plan)
    same = compare_with_lock(manifest, str(lock_path))
    assert same["breaking"] is False
    assert same["differences"] == []
    changed = dict(manifest)
    changed["snapshot_fingerprint"] = "0" * 64
    breaking = compare_with_lock(changed, str(lock_path))
    assert breaking["breaking"] is True
