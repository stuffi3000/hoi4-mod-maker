"""M3.4 deterministic foundation-manifest tests (first bounded slice)."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import uuid
from pathlib import Path

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.export_contract import StageResult, WrittenFile
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


def _ownership_fixture_stages():
    return [
        StageResult(
            stage="map_metadata",
            owned_files=("map/provinces.bmp", "map/default.map"),
            written=[],
        ),
        StageResult(
            stage="core_rasters",
            owned_files=("map/", "map/terrain/"),
            written=[WrittenFile("map/provinces.bmp", 10, "a" * 64)],
        ),
        StageResult(
            stage="state_geography",
            owned_files=("history/states/",),
            written=[WrittenFile("history/states/1-Foo.txt", 3, "c" * 64)],
        ),
    ]


def test_written_files_stage_ownership_resolution():
    plan = _base_plan()
    files = [
        WrittenFile("map/provinces.bmp", 10, "a" * 64),
        WrittenFile("map/terrain/colormap_water_0.dds", 5, "b" * 64),
        WrittenFile("map/default.map", 6, "d" * 64),
        WrittenFile("history/states/1-Foo.txt", 3, "c" * 64),
        WrittenFile("history/states/2-Bar.txt", 4, "e" * 64),
        WrittenFile("descriptor.mod", 7, "f" * 64),
    ]
    manifest = build_manifest_dict(plan, files, _ownership_fixture_stages())
    by_path = {entry["rel_path"]: entry for entry in manifest["written_files"]}
    assert by_path["map/provinces.bmp"]["stage"] == "core_rasters"
    assert by_path["map/terrain/colormap_water_0.dds"]["stage"] == "core_rasters"
    assert by_path["map/default.map"]["stage"] == "map_metadata"
    assert by_path["history/states/1-Foo.txt"]["stage"] == "state_geography"
    assert by_path["history/states/2-Bar.txt"]["stage"] == "state_geography"
    assert by_path["descriptor.mod"]["stage"] == "unowned"
    assert by_path["map/provinces.bmp"]["size"] == 10
    assert by_path["map/provinces.bmp"]["sha256"] == "a" * 64
    assert [entry["rel_path"] for entry in manifest["written_files"]] == sorted(by_path)


def test_stage_ownership_stable_under_shuffled_inputs_and_service_records():
    plan = _base_plan()
    stages = _ownership_fixture_stages()
    files = [
        WrittenFile("descriptor.mod", 7, "f" * 64),
        WrittenFile("map/provinces.bmp", 10, "a" * 64),
        WrittenFile("orphan.txt", 1, "9" * 64),
        WrittenFile("history/states/2-Bar.txt", 4, "e" * 64),
    ]
    service_record = StageResult(
        stage="",
        owned_files=("orphan.txt", "descriptor.mod"),
        written=[WrittenFile("orphan.txt", 1, "9" * 64)],
    )
    first = build_manifest_dict(plan, files, stages + [service_record])
    second = build_manifest_dict(
        plan, list(reversed(files)), [service_record] + list(reversed(stages))
    )
    assert first["written_files"] == second["written_files"]
    assert first["asset_resolutions"] == second["asset_resolutions"]
    assert first["stages"] == second["stages"]
    by_path = {entry["rel_path"]: entry for entry in first["written_files"]}
    assert by_path["orphan.txt"]["stage"] == "unowned"
    assert by_path["descriptor.mod"]["stage"] == "unowned"
    assert by_path["map/provinces.bmp"]["stage"] == "core_rasters"


def test_asset_source_and_output_hashes():
    raw = b"clean-world-normal-bytes"
    plan = _base_plan(assets={"map/world_normal.bmp": raw})
    staged_hash = "2" * 64
    out_hash = "1" * 64
    files = [
        WrittenFile("map/world_normal.bmp", len(raw), staged_hash),
        WrittenFile("map/provinces.bmp", 7, out_hash),
    ]
    manifest = build_manifest_dict(plan, files)
    by_path = {entry["rel_path"]: entry for entry in manifest["asset_resolutions"]}
    preserved = by_path["map/world_normal.bmp"]
    assert preserved["disposition"] == "preserved"
    assert preserved["provenance"] == "project-assets"
    assert preserved["size"] == len(raw)
    assert preserved["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert preserved["output_sha256"] == staged_hash
    generated = by_path["map/provinces.bmp"]
    assert generated["disposition"] == "generated"
    assert generated["provenance"] == "writer-generated"
    assert generated["reason"] == "export writers generate this file"
    assert generated["source_sha256"] == ""
    assert generated["output_sha256"] == out_hash
    assert plan.snapshot.assets["map/world_normal.bmp"] == raw


def test_asset_hashes_for_byte_like_and_missing_metadata():
    plan = _base_plan(
        assets={
            "custom/a.bin": bytearray(b"AAA"),
            "custom/b.bin": memoryview(b"BBB"),
            "custom/notes.txt": "text-is-not-bytes",
        }
    )
    manifest = build_manifest_dict(plan, [])
    by_path = {entry["rel_path"]: entry for entry in manifest["asset_resolutions"]}
    assert by_path["custom/a.bin"]["source_sha256"] == hashlib.sha256(b"AAA").hexdigest()
    assert by_path["custom/b.bin"]["source_sha256"] == hashlib.sha256(b"BBB").hexdigest()
    assert by_path["custom/a.bin"]["output_sha256"] == ""
    assert by_path["custom/notes.txt"]["source_sha256"] == ""
    assert by_path["custom/notes.txt"]["output_sha256"] == ""
    omitted = by_path["map/colors.txt"]
    assert omitted["disposition"] == "omitted"
    assert omitted["provenance"] == "profile-policy"
    assert omitted["source_sha256"] == ""
    assert omitted["output_sha256"] == ""
    assert plan.snapshot.assets["custom/notes.txt"] == "text-is-not-bytes"


def test_asset_lists_stable_under_shuffled_input_without_mutation():
    plan = _base_plan(assets={"map/world_normal.bmp": b"shuffled-bytes"})
    files = [
        {"rel_path": "b.txt", "size": 2, "sha256": "h2"},
        {"rel_path": "a.txt", "size": 1, "sha256": "h1"},
    ]
    files_before = copy.deepcopy(files)
    plan.asset_resolutions = [
        {"rel_path": "b.txt", "disposition": "generated", "provenance": "p",
         "reason": "r", "size": 2},
        {"rel_path": "a.txt", "disposition": "omitted", "provenance": "p",
         "reason": "r", "size": 0},
    ]
    resolutions_before = copy.deepcopy(plan.asset_resolutions)
    stages = [StageResult(stage="core_rasters", owned_files=("a.txt",), written=[])]
    first = build_manifest_dict(plan, files, stages)
    assert files == files_before
    assert plan.asset_resolutions == resolutions_before
    plan.asset_resolutions = list(reversed(plan.asset_resolutions))
    second = build_manifest_dict(plan, list(reversed(files)), list(reversed(stages)))
    assert first["written_files"] == second["written_files"]
    assert first["asset_resolutions"] == second["asset_resolutions"]
    assert [entry["rel_path"] for entry in first["written_files"]] == ["a.txt", "b.txt"]
    assert first["written_files"][0]["stage"] == "core_rasters"
    assert first["written_files"][1]["stage"] == "unowned"
    asset_by_path = {entry["rel_path"]: entry for entry in first["asset_resolutions"]}
    assert asset_by_path["b.txt"]["output_sha256"] == "h2"
    assert asset_by_path["b.txt"]["source_sha256"] == ""


def test_identity_invariant_to_inventory_stage_and_hashes():
    plan = _base_plan(assets={"map/world_normal.bmp": b"xyz"})
    empty = build_manifest_dict(plan, [])
    stages = [
        StageResult(
            stage="core_rasters",
            owned_files=("map/",),
            written=[WrittenFile("map/provinces.bmp", 1, "a" * 64)],
        )
    ]
    full = build_manifest_dict(
        plan,
        [WrittenFile("map/provinces.bmp", 1, "a" * 64), WrittenFile("zzz.txt", 1, "b" * 64)],
        stages,
    )
    assert full["identity"] == empty["identity"]
    assert manifest_identity_hash(full) == empty["identity"]["identity_hash"]
    assert full["sources"] == empty["sources"]
    assert full["target"]["identity"] == empty["target"]["identity"]
    assert full["written_files"] != empty["written_files"]
    assert full["asset_resolutions"] != empty["asset_resolutions"]
def test_validation_legacy_findings_serialized():
    from domain.validation import ValidationReport
    plan = _base_plan()
    manifest = build_manifest_dict(plan, [])
    validation = manifest["validation"]
    assert validation["source"] == "plan.findings"
    assert validation["context"] == "draft_preview"
    assert validation["total"] == len(plan.findings)
    assert validation["counts"]["warning"] + validation["counts"]["error"] + validation["counts"]["info"] + validation["counts"]["blocker"] == validation["total"]
    assert isinstance(validation["findings"], list)
    assert len(validation["findings"]) == validation["total"]
    gate = validation["gate"]
    assert gate["context"] == validation["context"]
    assert isinstance(gate["allowed"], bool)
    assert isinstance(gate["blocking"], list)
    assert isinstance(gate["visible_warnings"], list)
    assert isinstance(gate["waived"], list)
    assert validation["accepted_exceptions"] == []
    assert validation["accepted_keys"] == []
    expected = ValidationReport(findings=list(plan.findings), source="plan.findings", context="draft_preview")
    assert validation["total"] == expected.total
    assert validation["counts"] == expected.counts
    assert manifest["findings"] is not validation["findings"]


def test_validation_explicit_report_with_accepted_warning():
    from domain.validation import ValidationFinding, ValidationReport
    plan = _base_plan()
    finding = ValidationFinding(
        code="test.warn",
        severity="warning",
        message="explicit warning",
        layer="map",
        waivable=True,
        exception_id="EXP-001",
        exception_reason="reviewed",
        reviewed_by="qa",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )
    report = ValidationReport(findings=(finding,), source="test-source", context="draft_preview")
    accepted = [{"exception_id": "EXP-001", "reason": "reviewed"}]
    accepted_before = copy.deepcopy(accepted)
    manifest = build_manifest_dict(plan, [], validation_report=report, accepted_exceptions=accepted)
    validation = manifest["validation"]
    assert validation["source"] == "test-source"
    assert validation["context"] == "draft_preview"
    assert validation["total"] == 1
    assert validation["counts"] == {"info": 0, "warning": 1, "error": 0, "blocker": 0}
    assert validation["accepted_keys"] == ["EXP-001"]
    assert validation["accepted_exceptions"] == [{"exception_id": "EXP-001", "reason": "reviewed"}]
    assert accepted == accepted_before
    gate = validation["gate"]
    assert gate["context"] == "draft_preview"
    assert gate["allowed"] is True
    assert gate["blocking"] == []
    assert gate["visible_warnings"] == []
    assert len(gate["waived"]) == 1
    assert gate["waived"][0]["code"] == "test.warn"
    as_dict = build_manifest_dict(plan, [], validation_report=report.to_dict(), accepted_exceptions=["EXP-001"])
    assert as_dict["validation"]["total"] == 1
    assert as_dict["validation"]["accepted_keys"] == ["EXP-001"]
    assert len(as_dict["validation"]["gate"]["waived"]) == 1


def test_validation_accepted_from_snapshot_metadata():
    from domain.validation import ValidationFinding, ValidationReport
    from domain.project_meta import ProjectMeta
    plan = _base_plan()
    meta = ProjectMeta(validation_exceptions=[{"exception_id": "EXP-9", "code": "test.warn", "reason": "ok", "reviewed_by": "qa", "reviewed_at": "2026-01-01"}])
    meta_before = copy.deepcopy(meta.validation_exceptions)
    plan.snapshot.project_meta = meta
    finding = ValidationFinding(
        code="test.warn",
        severity="warning",
        message="meta warning",
        layer="map",
        waivable=True,
        exception_id="EXP-9",
        exception_reason="ok",
        reviewed_by="qa",
        reviewed_at="2026-01-01T00:00:00+00:00",
    )
    report = ValidationReport(findings=(finding,), source="meta-source", context="draft_preview")
    manifest = build_manifest_dict(plan, [], validation_report=report)
    assert manifest["validation"]["accepted_keys"] == ["EXP-9"]
    assert len(manifest["validation"]["gate"]["waived"]) == 1
    assert plan.snapshot.project_meta.validation_exceptions == meta_before


def test_validation_deterministic_context_selection():
    plan = _base_plan()
    for lifecycle, expected in (("draft", "draft_preview"), ("candidate", "foundation_candidate"), ("frozen", "freeze"), ("accepted", "accepted_lock")):
        plan.lifecycle = lifecycle
        manifest = build_manifest_dict(plan, [])
        assert manifest["validation"]["context"] == expected
        assert manifest["validation"]["gate"]["context"] == expected
    plan.lifecycle = "draft"
    overridden = build_manifest_dict(plan, [], validation_context="freeze")
    assert overridden["validation"]["context"] == "freeze"
    assert overridden["validation"]["gate"]["context"] == "freeze"
    fallback = build_manifest_dict(plan, [], validation_context="not-a-context")
    assert fallback["validation"]["context"] == "draft_preview"
    acceptance_plan = _base_plan(profile_name="acceptance")
    assert build_manifest_dict(acceptance_plan, [])["validation"]["context"] == "acceptance"
    first = build_manifest_dict(plan, [])
    second = build_manifest_dict(plan, [])
    assert first["validation"] == second["validation"]


def test_acceptance_default_and_explicit():
    plan = _base_plan()
    default = build_manifest_dict(plan, [])
    assert default["acceptance"] == {"status": "not_run"}
    assert default["engine_acceptance"] == {"status": "not_run"}
    explicit = {"status": "pass", "checks_passed": 7, "engine_version": "1.19.3"}
    explicit_before = copy.deepcopy(explicit)
    manifest = build_manifest_dict(plan, [], acceptance=explicit)
    assert manifest["acceptance"]["status"] == "pass"
    assert manifest["acceptance"]["checks_passed"] == 7
    assert manifest["acceptance"]["engine_version"] == "1.19.3"
    assert explicit == explicit_before
    assert list(manifest["acceptance"].keys())[0] == "status"
    assert manifest["engine_acceptance"] == manifest["acceptance"]
    via_alias = build_manifest_dict(plan, [], acceptance_result=explicit)
    assert via_alias["acceptance"] == manifest["acceptance"]
    plan.acceptance_result = {"status": "fail", "reason": "logs"}
    from_plan = build_manifest_dict(plan, [])
    assert from_plan["acceptance"]["status"] == "fail"
    delattr(plan, "acceptance_result")
    plan.engine_acceptance = {"status": "pass", "run_id": "abc"}
    from_engine = build_manifest_dict(plan, [])
    assert from_engine["acceptance"]["status"] == "pass"
    delattr(plan, "engine_acceptance")


def test_lock_compat_default_and_explicit():
    plan = _base_plan()
    default = build_manifest_dict(plan, [])
    assert default["lock_compat"] == {"status": "not_run", "breaking": False, "differences": []}
    explicit = {"status": "mismatch", "breaking": True, "differences": [{"field": "b"}, {"field": "a"}], "lock_hash": "abc"}
    explicit_before = copy.deepcopy(explicit)
    manifest = build_manifest_dict(plan, [], lock_compat=explicit)
    assert manifest["lock_compat"]["status"] == "mismatch"
    assert manifest["lock_compat"]["breaking"] is True
    assert manifest["lock_compat"]["differences"] == [{"field": "a"}, {"field": "b"}]
    assert manifest["lock_compat"]["lock_hash"] == "abc"
    assert explicit == explicit_before
    assert list(manifest["lock_compat"].keys())[:3] == ["status", "breaking", "differences"]
    compatible = build_manifest_dict(plan, [], lock_compat={"status": "compatible", "breaking": False, "differences": []})
    assert compatible["lock_compat"]["breaking"] is False


def test_identity_invariant_to_validation_acceptance_lock():
    from domain.validation import ValidationFinding, ValidationReport
    plan = _base_plan()
    base = build_manifest_dict(plan, [])
    finding = ValidationFinding(code="test.info", severity="info", message="note", layer="map")
    report = ValidationReport(findings=(finding,), source="explicit-source", context="draft_preview")
    changed = build_manifest_dict(
        plan,
        [],
        validation_report=report,
        acceptance={"status": "pass", "checks": 3},
        lock_compat={"status": "mismatch", "breaking": True, "differences": [{"field": "snapshot_fingerprint"}]},
    )
    assert changed["identity"] == base["identity"]
    assert manifest_identity_hash(changed) == base["identity"]["identity_hash"]
    assert changed["sources"] == base["sources"]
    assert changed["target"]["identity"] == base["target"]["identity"]
    assert changed["validation"] != base["validation"]
    assert changed["acceptance"] != base["acceptance"]
    assert changed["lock_compat"] != base["lock_compat"]


def test_malformed_optional_inputs_produce_safe_sections():
    plan = _base_plan()
    first = build_manifest_dict(plan, [], validation_report=12345, acceptance="bad", lock_compat=42, validation_context="nope", accepted_exceptions=12345)
    second = build_manifest_dict(plan, [], validation_report=12345, acceptance="bad", lock_compat=42, validation_context="nope", accepted_exceptions=12345)
    assert first["validation"]["total"] == 0
    assert first["validation"]["counts"] == {"info": 0, "warning": 0, "error": 0, "blocker": 0}
    assert first["validation"]["findings"] == []
    assert first["validation"]["context"] == "draft_preview"
    assert first["validation"]["gate"]["allowed"] is True
    assert first["acceptance"] == {"status": "not_run"}
    assert first["lock_compat"] == {"status": "not_run", "breaking": False, "differences": []}
    assert first["validation"] == second["validation"]
    assert first["acceptance"] == second["acceptance"]
    assert first["lock_compat"] == second["lock_compat"]


def test_write_manifest_forwards_validation_acceptance_lock(m3_4_tmp):
    import json
    from pathlib import Path
    from domain.validation import ValidationFinding, ValidationReport
    from services.export_manifest import write_manifest
    plan = _base_plan()
    finding = ValidationFinding(code="test.warn", severity="warning", message="file check", layer="map")
    report = ValidationReport(findings=(finding,), source="file-source", context="draft_preview")
    first_path = write_manifest(
        str(m3_4_tmp),
        plan,
        [],
        validation_report=report,
        acceptance={"status": "pass"},
        lock_compat={"status": "compatible", "breaking": False, "differences": []},
        manifest_name="first.json",
    )
    second_path = write_manifest(
        str(m3_4_tmp),
        plan,
        [],
        validation_report=report,
        acceptance={"status": "pass"},
        lock_compat={"status": "compatible", "breaking": False, "differences": []},
        manifest_name="second.json",
    )
    first_data = json.loads(Path(first_path).read_text(encoding="utf-8"))
    second_data = json.loads(Path(second_path).read_text(encoding="utf-8"))
    assert first_data["validation"]["source"] == "file-source"
    assert first_data["acceptance"] == {"status": "pass"}
    assert first_data["lock_compat"] == {"status": "compatible", "breaking": False, "differences": []}
    assert first_data["validation"] == second_data["validation"]
    assert first_data["acceptance"] == second_data["acceptance"]
    assert first_data["lock_compat"] == second_data["lock_compat"]
    assert first_data["identity"] == second_data["identity"]
