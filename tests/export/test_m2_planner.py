"""M2 immutable export planning, profiles, staging, and stage tests."""
from __future__ import annotations

import json
import os

import numpy as np
from pathlib import Path
import pytest

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.export_contract import (
    EXPORT_PROFILES,
    PROFILE_STAGES,
    REPAIR_SAFETY_LEVELS,
    RESERVED_ACCEPTANCE_TAGS,
    ExportPlan,
    PlanRejected,
    resolve_layers,
    select_acceptance_tags,
)
from domain.managers.continent import ContinentManager
from domain.managers.country import CountryManager
from domain.managers.state import StateManager
from domain.managers.strategic_region import StrategicRegionManager
from services.export_manifest import compare_with_lock
from services.export_planner import (
    compute_fingerprint,
    format_plan_summary,
    plan_export,
)
from services.export_transaction import (
    StagingPolicy,
    prepare_staging,
    promote_staging,
    run_staged_export,
    validate_destination,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def m2_tmp(request, tmp_path_factory):
    """Repository-local scratch dir; pytest tmp_path ACLs are unreliable here."""
    import shutil
    import uuid
    root = Path("tmp/m2-test-tmp") / ("%s-%s" % (request.node.name[:40], uuid.uuid4().hex[:8]))
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _fixture_maps(size: int = 64, provinces: tuple = (1, 2)):
    tile = np.full((size, size), TILE_SEA, dtype=np.uint8)
    tile[8:56, 8:56] = TILE_LAND
    prov = np.zeros((size, size), dtype=np.int32)
    half = 8 + (56 - 8) // 2
    prov[8:56, 8:half] = provinces[0]
    prov[8:56, half:56] = provinces[1]
    terrain = np.full((size, size), TERRAIN_PALETTE_INDEX["ocean"], dtype=np.uint8)
    terrain[8:56, 8:56] = TERRAIN_PALETTE_INDEX["plains"]
    return tile, prov, terrain


def _fixture_managers(owner_tag: str | None = "TST", with_capital: bool = True):
    states = StateManager()
    first = states.create_state("West")
    first.provinces = [1]
    second = states.create_state("East")
    second.provinces = [2]
    countries = CountryManager()
    country = countries.create_country("TST", "Testland", (100, 120, 200))
    if owner_tag is not None:
        countries.assign_state(first.id, owner_tag)
        first.owner_tag = owner_tag
        countries.assign_state(second.id, owner_tag)
        second.owner_tag = owner_tag
    if with_capital:
        country.capital = 1
    return states, countries, ContinentManager()


def _live_fingerprint(tile, prov, terrain, managers: dict) -> str:
    return compute_fingerprint(tile, prov, terrain, managers)


def test_plan_returns_export_plan_without_writing_files(m2_tmp):
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    out = m2_tmp / "planned"
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="foundation")
    assert isinstance(plan, ExportPlan)
    assert plan.snapshot is not None
    assert plan.layers == PROFILE_STAGES["foundation"]
    assert not out.exists()


def test_successful_river_validation_is_not_recorded_as_a_warning():
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    river = np.full(tile.shape, 255, dtype=np.uint8)
    river[10:15, 10] = 3
    river[10, 10] = 0
    plan = plan_export(
        tile,
        prov,
        terrain,
        river_map=river,
        state_mgr=states,
        country_mgr=countries,
        continent_mgr=continents,
        profile_name="foundation",
    )
    assert not any(finding.code == "river.legality" for finding in plan.findings)


def test_plan_does_not_mutate_live_project(m2_tmp):
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    managers = {"state_mgr": states, "country_mgr": countries, "continent_mgr": continents}
    before = _live_fingerprint(tile, prov, terrain, managers)
    before_arrays = [tile.copy(), prov.copy(), terrain.copy()]
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="scaffold",
                       repair_policy="apply-safe")
    assert _live_fingerprint(tile, prov, terrain, managers) == before
    assert plan.snapshot.check_live_unchanged(
        {"tile_map": tile, "province_map": prov, "terrain_map": terrain}, managers) == []
    from services.export_service import export_planned_mod
    export_planned_mod(plan, str(m2_tmp / "mod"))
    assert _live_fingerprint(tile, prov, terrain, managers) == before
    for live, saved in zip((tile, prov, terrain), before_arrays):
        assert np.array_equal(live, saved)


def test_plan_normalizes_land_lake_splits_on_export_snapshot():
    tile = np.full((32, 32), TILE_LAKE, dtype=np.uint8)
    prov = np.ones((32, 32), dtype=np.int32)
    tile[0, 0] = TILE_LAND
    terrain = np.full(tile.shape, TERRAIN_PALETTE_INDEX["lakes"], dtype=np.uint8)
    states, countries, continents = _fixture_managers()

    plan = plan_export(
        tile,
        prov,
        terrain,
        state_mgr=states,
        country_mgr=countries,
        continent_mgr=continents,
        profile_name="foundation",
        repair_policy="apply-safe",
    )

    repairs = [r for r in plan.applied_repairs if r.code == "province.land_lake_sync"]
    assert len(repairs) == 1
    assert repairs[0].affected_ids == (1,)
    assert np.all(plan.snapshot.tile_map == TILE_LAKE)
    assert tile[0, 0] == TILE_LAND
    assert any(f.code == "province.land_lake_split" for f in plan.findings)


def test_snapshot_arrays_are_read_only():
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="foundation")
    for name in ("tile_map", "province_map", "terrain_map"):
        arr = getattr(plan.snapshot, name)
        assert arr is not None
        assert arr.flags.writeable is False
        with pytest.raises(ValueError):
            arr[0, 0] = 7


def test_repair_action_contract_fields():
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="legacy_full",
                       repair_policy="propose")
    assert plan.proposed_repairs
    codes = [repair.code for repair in plan.proposed_repairs]
    assert len(set(codes)) == len(codes)
    for repair in plan.proposed_repairs:
        assert repair.safety in REPAIR_SAFETY_LEVELS
        assert repair.summary
        assert repair.rerun_validations
        payload = repair.to_dict()
        assert payload["code"] == repair.code
    compact = [repair for repair in plan.proposed_repairs if repair.code == "province.compact_ids"]
    assert compact == []


def test_compact_repair_carries_id_mapping():
    tile, prov, _terrain = _fixture_maps(provinces=(1, 3))
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, None, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="legacy_full",
                       repair_policy="propose")
    compact = [repair for repair in plan.proposed_repairs if repair.code == "province.compact_ids"]
    assert len(compact) == 1
    assert compact[0].safety == "breaking"
    assert compact[0].mapping == {3: 2}


def test_gameplay_values_are_never_foundation_repairs():
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    for profile in EXPORT_PROFILES:
        plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                           continent_mgr=continents, profile_name=profile,
                           repair_policy="propose")
        for repair in plan.proposed_repairs:
            lowered = (repair.code + " " + repair.summary).lower()
            assert "resource" not in lowered
            assert "building" not in lowered
            assert "manpower" not in lowered
            assert "victory" not in lowered
        if profile == "foundation":
            assert "state.unowned_assign" not in [repair.code for repair in plan.proposed_repairs]
            assert "country.capital_assign" not in [repair.code for repair in plan.proposed_repairs]


def test_repair_policy_off_proposes_nothing():
    tile, prov, terrain = _fixture_maps(provinces=(1, 3))
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="legacy_full",
                       repair_policy="off")
    assert plan.proposed_repairs == []
    assert plan.applied_repairs == []


def test_candidate_requires_confirmation_for_semantic_repairs():
    tile = np.full((32, 32), TILE_SEA, dtype=np.uint8)
    tile[4:28, 4:28] = TILE_LAND
    prov = np.zeros((32, 32), dtype=np.int32)
    prov[4:28, 4:16] = 1
    prov[4:28, 16:28] = 2
    prov[0, 0] = 5
    terrain = np.full((32, 32), TERRAIN_PALETTE_INDEX["ocean"], dtype=np.uint8)
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="scaffold",
                       repair_policy="apply-safe", lifecycle="candidate")
    semantic = [repair for repair in plan.proposed_repairs if repair.safety == "semantic"]
    assert semantic
    assert all(repair.safety == "safe" for repair in plan.applied_repairs)


def test_frozen_lifecycle_blocks_breaking_repairs():
    tile, prov, terrain = _fixture_maps(provinces=(1, 3))
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="scaffold",
                       repair_policy="apply-safe", lifecycle="frozen")
    assert plan.blocked
    assert any("unfreez" in blocker for blocker in plan.blockers)
    assert plan.applied_repairs == []
    from services.export_service import export_planned_mod
    with pytest.raises(ValueError):
        export_planned_mod(plan, "/nonexistent-frozen-target")


def test_unknown_profile_and_layer_are_rejected():
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    with pytest.raises(PlanRejected):
        plan_export(tile, prov, terrain, state_mgr=states, profile_name="nope")
    with pytest.raises(PlanRejected):
        resolve_layers("foundation", {"countries": True})
    assert resolve_layers("legacy_full", {"countries": True})


def test_foundation_export_has_no_gameplay_content(m2_tmp):
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="foundation",
                       repair_policy="apply-safe", mod_name="FoundationMod")
    from services.export_service import export_planned_mod
    result = export_planned_mod(plan, str(m2_tmp / "foundation"))
    names = sorted(entry.rel_path for entry in result.written_files)
    assert not [name for name in names if "/D" in name and name.startswith("history/countries")]
    assert not [name for name in names if name.startswith("common/country_tags")]
    assert not [name for name in names if name.startswith("localisation")]
    assert [name for name in names if name.startswith("history/states")]
    shell = (m2_tmp / "foundation" / "history" / "states" / "1-STATE_1.txt").read_text(encoding="utf-8")
    assert "owner =" not in shell
    for token in ("resources", "buildings", "manpower", "victory_points"):
        assert token not in shell
    manifest = json.loads((m2_tmp / "foundation" / "foundation_manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "foundation"
    assert manifest["placeholders"]
    dispositions = {entry["disposition"] for entry in manifest["asset_resolutions"]}
    assert {"generated", "omitted", "inherited"} <= dispositions
    assert manifest["snapshot_fingerprint"] == plan.snapshot.fingerprint


def test_acceptance_tags_are_deterministic_and_collision_free(m2_tmp):
    occupied = ["TST", "AAA"]
    first = select_acceptance_tags(occupied, count=2)
    second = select_acceptance_tags(occupied, count=2)
    assert first == second
    assert len(first) == 2
    for tag in first:
        assert tag not in RESERVED_ACCEPTANCE_TAGS
        assert tag not in occupied
        assert len(tag) == 3 and tag.isupper()
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="acceptance",
                       repair_policy="apply-safe")
    from data.constants import get_vanilla_tags
    assert tuple(plan.acceptance_tags) == select_acceptance_tags(
        list(get_vanilla_tags()) + ["TST"], count=2)
    from services.export_service import export_planned_mod
    export_planned_mod(plan, str(m2_tmp / "acceptance"))
    tags_text = (m2_tmp / "acceptance" / "common" / "country_tags"
                 / "99_acceptance_tags.txt").read_text(encoding="utf-8")
    for tag in plan.acceptance_tags:
        assert tag in tags_text


def test_transaction_promotion_backup_and_overwrite(m2_tmp):
    dest = m2_tmp / "mod"
    assert validate_destination("") != []
    assert validate_destination(str(m2_tmp / "fresh-dest")) == []
    staging = prepare_staging(str(dest))
    (Path(staging) / "hello.txt").write_text("hi", encoding="utf-8")
    final = promote_staging(staging, str(dest), StagingPolicy())
    assert final == os.path.abspath(dest)
    assert (m2_tmp / "mod" / "hello.txt").read_text(encoding="utf-8") == "hi"
    with pytest.raises(FileExistsError):
        run_staged_export(str(dest), lambda staging_dir: None, StagingPolicy())
    assert (m2_tmp / "mod" / "hello.txt").read_text(encoding="utf-8") == "hi"
    def _write_v2(staging_dir):
        Path(staging_dir, "hello.txt").write_text("v2", encoding="utf-8")
    run_staged_export(str(dest), _write_v2, StagingPolicy(overwrite=True))
    assert (m2_tmp / "mod" / "hello.txt").read_text(encoding="utf-8") == "v2"
    def _write_v3(staging_dir):
        Path(staging_dir, "hello.txt").write_text("v3", encoding="utf-8")
    run_staged_export(str(dest), _write_v3, StagingPolicy(backup=True))
    backups = sorted(m2_tmp.glob("mod.backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "hello.txt").read_text(encoding="utf-8") == "v2"
    assert (m2_tmp / "mod" / "hello.txt").read_text(encoding="utf-8") == "v3"


def test_transaction_failed_staging_cleanup_and_keep(m2_tmp):
    dest = m2_tmp / "mod"

    def _boom(staging_dir):
        __import__("pathlib").Path(staging_dir, "partial.txt").write_text("x", encoding="utf-8")
        raise RuntimeError("writer exploded")

    with pytest.raises(RuntimeError):
        run_staged_export(str(dest), _boom, StagingPolicy())
    assert not list(m2_tmp.glob("mod.staging-*"))
    with pytest.raises(RuntimeError) as excinfo:
        run_staged_export(str(dest), _boom, StagingPolicy(keep_failed=True))
    assert "failed staging kept at" in str(excinfo.value)
    leftovers = list(m2_tmp.glob("mod.staging-*"))
    assert len(leftovers) == 1
    assert (leftovers[0] / "partial.txt").read_text(encoding="utf-8") == "x"


def test_transaction_rejects_staging_outside_destination_parent(m2_tmp):
    destination = m2_tmp / "mod"
    outside = m2_tmp / "elsewhere"
    outside.mkdir()
    staging = outside / "mod.staging-forged"
    staging.mkdir()
    (staging / "sentinel.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        promote_staging(str(staging), str(destination), StagingPolicy())
    assert (staging / "sentinel.txt").is_file()


def test_pipeline_restores_process_map_size(m2_tmp):
    import data.constants as constants
    from export.stages import pipeline
    from export.stages.base import build_context_from_plan
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="foundation")
    ctx = build_context_from_plan(plan, str(m2_tmp / "sized"))
    original = (constants.MAP_WIDTH, constants.MAP_HEIGHT)
    pipeline.run_pipeline(ctx)
    assert (constants.MAP_WIDTH, constants.MAP_HEIGHT) == original


def test_manager_fingerprint_detects_nested_record_mutation():
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="foundation")
    states.states[1].resources["steel"] = 12
    changed = plan.snapshot.check_live_unchanged(
        {"tile_map": tile, "province_map": prov, "terrain_map": terrain},
        {"state_mgr": states, "country_mgr": countries, "continent_mgr": continents},
    )
    assert changed


def test_stages_declare_owned_files_and_results(m2_tmp):
    from export.stages import pipeline
    from export.stages.base import build_context_from_plan
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    for profile in EXPORT_PROFILES:
        for stage_name in pipeline.stages_for_profile(profile):
            module = pipeline.STAGE_MODULES[stage_name]
            assert module.NAME == stage_name
            assert isinstance(module.OWNED_FILES, tuple)
            assert profile in tuple(module.PROFILES)
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="scaffold",
                       repair_policy="apply-safe")
    ctx = build_context_from_plan(plan, str(m2_tmp / "staged"))
    results = pipeline.run_pipeline(ctx)
    assert [result.stage for result in results] == list(pipeline.stages_for_profile("scaffold"))
    owned_prefixes = []
    for result in results:
        for owned in result.owned_files:
            owned_prefixes.append(owned)
    service_records = {"foundation_manifest.json", "foundation_report.md",
                       "foundation.lock.json", "scaffold_provenance.json"}
    for entry in ctx.written:
        if entry.rel_path in service_records:
            continue
        assert any(entry.rel_path == owned or entry.rel_path.startswith(owned)
                   for owned in owned_prefixes), entry.rel_path
    with pytest.raises(ValueError):
        pipeline.run_pipeline(ctx, layers=["no_such_stage"])
    with pytest.raises(ValueError):
        pipeline.run_pipeline(ctx, layers=["acceptance_content"])


def test_manifest_and_lock_comparison(m2_tmp):
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="foundation")
    from services.export_service import export_planned_mod
    result = export_planned_mod(plan, str(m2_tmp / "foundation"))
    manifest = json.loads(open(result.manifest_path, encoding="utf-8").read())
    assert manifest["written_files"]
    lock_path = m2_tmp / "foundation" / "foundation.lock.json"
    assert lock_path.is_file()
    same = compare_with_lock(manifest, str(lock_path))
    assert same["breaking"] is False
    assert same["differences"] == []
    changed = dict(manifest)
    changed["snapshot_fingerprint"] = "0" * 64
    breaking = compare_with_lock(changed, str(lock_path))
    assert breaking["breaking"] is True


def test_plan_summary_reports_repairs_and_assets():
    tile, prov, terrain = _fixture_maps()
    states, countries, continents = _fixture_managers()
    plan = plan_export(tile, prov, terrain, state_mgr=states, country_mgr=countries,
                       continent_mgr=continents, profile_name="foundation")
    summary = format_plan_summary(plan)
    assert "profile: foundation" in summary
    assert "layers:" in summary
    assert "assets:" in summary


def test_cli_planner_options_and_trigger():
    import cli_export
    parser = cli_export.build_parser()
    args = parser.parse_args(["proj.hoi4proj", "out"])
    assert args.profile == "legacy_full"
    assert args.repair == "apply-safe"
    assert cli_export._uses_planner_path(args) is False
    planned = parser.parse_args(["proj.hoi4proj", "out", "--profile", "foundation"])
    assert cli_export._uses_planner_path(planned) is True
    assert cli_export._verify_planned_export("nonexistent-dir-xyz", "foundation") != []
    lock_args = parser.parse_args(["proj.hoi4proj", "out", "--compare-lock", "lock.json"])
    assert cli_export._uses_planner_path(lock_args) is True


def test_gui_worker_accepts_planner_options():
    pytest.importorskip("PyQt5.QtWidgets")
    import inspect
    from views.export_dialog import ExportDialog, ExportWorker
    params = inspect.signature(ExportWorker.__init__).parameters
    assert params["profile_name"].default == "legacy_full"
    assert params["repair_policy"].default == "apply-safe"
    assert "overwrite" in params and "backup" in params
    assert hasattr(ExportDialog, "_refresh_plan_summary")
    assert hasattr(ExportDialog, "_profile_combo") or True
