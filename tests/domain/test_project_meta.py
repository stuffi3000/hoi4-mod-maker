"""M1.3 project-metadata tests (small in-memory projects, no game install)."""
from __future__ import annotations

import json
from zipfile import ZipFile

import numpy as np
import pytest

from domain.managers.country import CountryManager
from domain.managers.state import StateManager
from domain.project_io import (
    load_project,
    load_project_with_meta,
    read_project_meta,
    save_project,
)
from domain.project_meta import (
    CURRENT_SCHEMA_VERSION,
    PROJECT_META_FILENAME,
    NewerSchemaError,
    ProjectMeta,
    UnknownSchemaError,
    backup_archive_before_migration,
    default_meta,
    infer_meta_for_legacy_project,
)

pytestmark = pytest.mark.unit


def _managers():
    states = StateManager()
    state = states.create_state([1])
    state.name = "Test"
    countries = CountryManager()
    return states, countries


def _arrays():
    tile = np.ones((2, 2), dtype=np.uint8)
    prov = np.ones((2, 2), dtype=np.int32)
    terrain = np.zeros((2, 2), dtype=np.uint8)
    height = np.ones((2, 2), dtype=np.float32)
    return tile, prov, terrain, height


def test_default_and_inferred_meta():
    meta = default_meta(width=10, height=20)
    assert meta.schema_version == CURRENT_SCHEMA_VERSION
    assert meta.lifecycle == "draft"
    assert meta.width == 10 and meta.height == 20
    assert meta.needs_target_confirmation is False
    inferred = infer_meta_for_legacy_project(width=5, height=6)
    assert inferred.lifecycle == "draft"
    assert inferred.needs_target_confirmation is True
    assert inferred.width == 5 and inferred.height == 6


def test_meta_round_trip():
    meta = default_meta(width=7, height=8, profile_id="hoi4-1.19")
    meta.lifecycle = "candidate"
    meta.adjacency_review = "none_intended"
    meta.validation_exceptions = [{"code": "demo", "reason": "test"}]
    data = meta.to_dict()
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION
    assert data["dimensions"] == {"width": 7, "height": 8}
    restored = ProjectMeta.from_dict(json.loads(json.dumps(data)))
    assert restored.lifecycle == "candidate"
    assert restored.adjacency_review == "none_intended"
    assert restored.validation_exceptions == [{"code": "demo", "reason": "test"}]


def test_unknown_schema_rejected():
    with pytest.raises((UnknownSchemaError, NewerSchemaError)):
        ProjectMeta.from_dict({"schema_version": 9999})


def test_save_and_load_with_meta_preserves_managers(tmp_path):
    states, countries = _managers()
    tile, prov, terrain, height = _arrays()
    path = str(tmp_path / "with_meta.hoi4proj")
    meta = default_meta(width=2, height=2)
    meta.profile_id = "hoi4-1.19"
    save_project(
        path,
        tile_map=tile,
        province_map=prov,
        terrain_map=terrain,
        height_map=height,
        state_mgr=states,
        country_mgr=countries,
        project_meta=meta,
    )
    with ZipFile(path, "r") as zf:
        assert PROJECT_META_FILENAME in zf.namelist()
        assert "states.json" in zf.namelist()
    on_disk = read_project_meta(path)
    assert on_disk is not None
    assert on_disk.profile_id == "hoi4-1.19"
    assert on_disk.width == 2 and on_disk.height == 2
    fresh_states, fresh_countries = StateManager(), CountryManager()
    result = load_project_with_meta(path, fresh_states, fresh_countries)
    assert len(result) == 8
    meta_loaded = result[-1]
    assert meta_loaded.profile_id == "hoi4-1.19"
    assert fresh_states.get_state(1) is not None
    assert fresh_states.get_state(1).name == "Test"


def test_legacy_archive_loads_as_draft_requiring_confirmation(tmp_path):
    states, countries = _managers()
    tile, prov, terrain, height = _arrays()
    path = str(tmp_path / "legacy.hoi4proj")
    save_project(
        path,
        tile_map=tile,
        province_map=prov,
        terrain_map=terrain,
        height_map=height,
        state_mgr=states,
        country_mgr=countries,
    )
    with ZipFile(path, "r") as zf:
        assert PROJECT_META_FILENAME not in zf.namelist()
    assert read_project_meta(path) is None
    fresh_states, fresh_countries = StateManager(), CountryManager()
    result = load_project_with_meta(path, fresh_states, fresh_countries)
    meta = result[-1]
    assert meta.lifecycle == "draft"
    assert meta.needs_target_confirmation is True
    assert meta.schema_version == CURRENT_SCHEMA_VERSION
    # Legacy direct loader still works and managers are intact.
    legacy_states, legacy_countries = StateManager(), CountryManager()
    load_project(path, legacy_states, legacy_countries)
    assert legacy_states.get_state(1) is not None


def test_newer_schema_load_rejected_without_mutation(tmp_path):
    states, countries = _managers()
    tile, prov, terrain, height = _arrays()
    path = str(tmp_path / "newer.hoi4proj")
    save_project(
        path,
        tile_map=tile,
        province_map=prov,
        terrain_map=terrain,
        height_map=height,
        state_mgr=states,
        country_mgr=countries,
    )
    with ZipFile(path, "a") as zf:
        zf.writestr(
            PROJECT_META_FILENAME,
            json.dumps({"schema_version": 9999, "lifecycle": "draft"}),
        )
    with pytest.raises(NewerSchemaError):
        read_project_meta(path)
    probe_states, probe_countries = StateManager(), CountryManager()
    sentinel = probe_states.create_state([9])
    assert sentinel is not None
    with pytest.raises(NewerSchemaError):
        load_project(path, probe_states, probe_countries)
    # Save must refuse to overwrite a newer archive without explicit opt-in.
    with pytest.raises(NewerSchemaError):
        save_project(
            path,
            tile_map=tile,
            province_map=prov,
            terrain_map=terrain,
            height_map=height,
            state_mgr=states,
            country_mgr=countries,
            project_meta=default_meta(width=2, height=2),
        )
    with ZipFile(path, "r") as zf:
        raw = json.loads(zf.read(PROJECT_META_FILENAME).decode("utf-8"))
        assert raw["schema_version"] == 9999


def test_invalid_metadata_is_rejected_before_overwriting_output(tmp_path):
    states, countries = _managers()
    tile, prov, terrain, height = _arrays()
    path = tmp_path / "protected.hoi4proj"
    original = b"keep this archive intact"
    path.write_bytes(original)
    invalid = ProjectMeta(schema_version=9999)

    with pytest.raises(UnknownSchemaError):
        save_project(
            str(path),
            tile_map=tile,
            province_map=prov,
            terrain_map=terrain,
            height_map=height,
            state_mgr=states,
            country_mgr=countries,
            project_meta=invalid,
        )
    assert path.read_bytes() == original


def test_backup_preserved_before_migration(tmp_path):
    states, countries = _managers()
    tile, prov, terrain, height = _arrays()
    path = str(tmp_path / "migrate.hoi4proj")
    save_project(
        path,
        tile_map=tile,
        province_map=prov,
        terrain_map=terrain,
        height_map=height,
        state_mgr=states,
        country_mgr=countries,
    )
    backup = backup_archive_before_migration(path)
    import os

    assert os.path.isfile(backup)
    assert backup != path
    with ZipFile(backup, "r") as zf:
        assert "states.json" in zf.namelist()


def test_project_model_round_trip_with_meta(tmp_path):
    from model.project import Project

    project = Project()
    project.new_project(4, 4)
    assert project.project_meta.lifecycle == "draft"
    assert (project.project_meta.width, project.project_meta.height) == (4, 4)
    project.set_game_target(None, profile_id="hoi4-1.19")
    target_path = str(tmp_path / "model_meta.hoi4proj")
    project.save(target_path)
    with ZipFile(target_path, "r") as zf:
        assert PROJECT_META_FILENAME in zf.namelist()
    reloaded = Project()
    reloaded.load(target_path)
    assert reloaded.project_meta.profile_id == "hoi4-1.19"
    assert (reloaded.project_meta.width, reloaded.project_meta.height) == (4, 4)
    assert reloaded.map_data.tile_map.shape == (4, 4)


def test_legacy_project_migrates_on_save_and_preserves_sidecar(tmp_path):
    from model.project import Project

    states, countries = _managers()
    tile, prov, terrain, height = _arrays()
    legacy_path = str(tmp_path / "legacy_model.hoi4proj")
    save_project(
        legacy_path,
        tile_map=tile,
        province_map=prov,
        terrain_map=terrain,
        height_map=height,
        state_mgr=states,
        country_mgr=countries,
    )
    asset_path = tmp_path / "legacy_model.hoi4proj_assets" / "map" / "custom.dds"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"legacy asset")
    (tmp_path / "legacy_model.hoi4proj_assets" / "_manifest.txt").write_text(
        "CLEAN\tmap/custom.dds\t12\n",
        encoding="utf-8",
    )

    project = Project()
    project.load(legacy_path)
    assert project.project_meta.needs_target_confirmation is True
    migrated_path = str(tmp_path / "migrated.hoi4proj")
    project.save(migrated_path)

    with ZipFile(migrated_path, "r") as zf:
        assert PROJECT_META_FILENAME in zf.namelist()
        assert zf.read("states.json")
    migrated_asset = tmp_path / "migrated.hoi4proj_assets" / "map" / "custom.dds"
    assert migrated_asset.read_bytes() == b"legacy asset"
