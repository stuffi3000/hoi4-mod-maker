"""M3.2b readiness/export-service shared-report wiring tests."""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from domain.managers.continent import ContinentManager
from domain.managers.country import CountryManager
from domain.managers.state import StateManager, StateData
from domain.managers.strategic_region import StrategicRegionManager
from domain.validation import ValidationReport
from services import export_service, readiness_service
from services.export_service import ExportReport, pre_export_check_and_fix, validate_before_export
from services.readiness_service import CheckItem, check_project_readiness, check_project_readiness_report
from services.validation_service import (
    PREFLIGHT_LAYER,
    PREFLIGHT_SOURCE,
    preflight_message_code,
    report_from_preflight_messages,
)

pytestmark = pytest.mark.unit

EXPECTED_READINESS_CODES = frozenset({
    "readiness.provinces",
    "readiness.land",
    "readiness.states",
    "readiness.countries",
    "readiness.strategic_regions",
    "readiness.continents",
    "readiness.terrain",
    "readiness.heightmap",
    "readiness.assets",
    "readiness.map_dimensions",
})


def _map_source(h=8, w=16):
    tile_map = np.full((h, w), TILE_SEA, dtype=np.uint8)
    tile_map[h // 2:, :] = TILE_LAND
    province_map = np.zeros((h, w), dtype=np.int32)
    province_map[:h // 2, :] = 1
    province_map[h // 2:, :] = 2
    terrain_map = np.ones((h, w), dtype=np.uint8)
    height_map = np.full((h, w), 90, dtype=np.uint8)
    height_map[h // 2:, :] = 120
    return SimpleNamespace(
        tile_map=tile_map, province_map=province_map,
        terrain_map=terrain_map, height_map=height_map,
    )


def _project(with_state=True, with_country=True):
    state_mgr = StateManager()
    country_mgr = CountryManager()
    if with_state:
        state_mgr._states[1] = StateData(
            id=1, name="S1", provinces=[2], owner_tag="TST")
        state_mgr._province_to_state = {2: 1}
        state_mgr._next_id = 2
    if with_country:
        country_mgr.create_country("TST", "Test", (10, 20, 30))
        country_mgr.set_capital("TST", 2)
        country_mgr.assign_state(1, "TST")
    sr_mgr = StrategicRegionManager()
    sr_mgr.create_region()
    cont_mgr = ContinentManager()
    return SimpleNamespace(
        state_mgr=state_mgr, country_mgr=country_mgr,
        strategic_region_mgr=sr_mgr, continent_mgr=cont_mgr,
        assets={},
    )


def test_check_item_backward_compat():
    legacy_four = CheckItem("name", "ok", "detail", False)
    assert legacy_four.count == 0
    assert legacy_four.code == ""
    legacy_five = CheckItem("name", "warning", "detail", True, 7)
    assert legacy_five.count == 7
    assert legacy_five.code == ""
    assert CheckItem("n", "ok", "d", False, 0, "readiness.provinces").code == "readiness.provinces"


def test_readiness_items_carry_explicit_stable_codes():
    items = check_project_readiness(_project(), _map_source())
    assert items
    assert all(item.code for item in items)
    assert all(item.code in EXPECTED_READINESS_CODES for item in items)
    assert {item.code for item in items} == {
        "readiness.provinces", "readiness.states", "readiness.countries",
        "readiness.strategic_regions", "readiness.continents",
        "readiness.terrain", "readiness.heightmap",
    }
    assert items[0].code == "readiness.provinces"

    empty_src = _map_source()
    empty_src.province_map[:] = 0
    empty_items = check_project_readiness(_project(), empty_src)
    assert [item.code for item in empty_items] == ["readiness.provinces"]

    no_land_src = _map_source()
    no_land_src.tile_map[:] = TILE_SEA
    no_land_items = check_project_readiness(_project(), no_land_src)
    assert [item.code for item in no_land_items] == ["readiness.land"]

    bare_items = check_project_readiness(
        _project(with_state=False, with_country=False), _map_source())
    bare_codes = {item.code for item in bare_items}
    assert {"readiness.states", "readiness.countries"} <= bare_codes

    from services import game_profile_service as profiles
    profile = profiles.get_default_profile()
    dim_items = check_project_readiness(_project(), _map_source(), profile=profile, dimensions=(100, 100))
    assert [item.code for item in dim_items] == ["readiness.map_dimensions"]


def test_readiness_codes_independent_of_display_names(monkeypatch):
    monkeypatch.setattr(readiness_service, "tr", lambda key, *args, **kwargs: "XX-" + str(key))
    items = check_project_readiness(_project(), _map_source())
    assert all(item.name.startswith("XX-") for item in items)
    assert all(item.code in EXPECTED_READINESS_CODES for item in items)
    assert items[0].code == "readiness.provinces"


def test_readiness_report_calls_checks_once(monkeypatch):
    original = readiness_service.check_project_readiness
    calls = []

    def _counting(project, map_source, profile=None, dimensions=None):
        calls.append((profile, dimensions))
        return original(project, map_source, profile=profile, dimensions=dimensions)

    monkeypatch.setattr(readiness_service, "check_project_readiness", _counting)
    project, source = _project(), _map_source()
    report = check_project_readiness_report(project, source)
    assert len(calls) == 1
    assert calls[0] == (None, None)
    assert isinstance(report, ValidationReport)
    assert report.source == "readiness"
    assert report.context == "draft_preview"
    expected = original(project, source)
    assert [finding.code for finding in report.findings] == [item.code for item in expected]
    assert [finding.message for finding in report.findings] == [item.detail for item in expected]

    from services import game_profile_service as profiles
    profile = profiles.get_default_profile()
    report = check_project_readiness_report(project, source, profile=profile, dimensions=(100, 100))
    assert len(calls) == 2
    assert calls[1][0] is profile and calls[1][1] == (100, 100)
    assert report.context == "draft_preview"


def test_readiness_report_context_and_gate():
    report = check_project_readiness_report(_project(), _map_source(), context="foundation_candidate")
    assert report.context == "foundation_candidate"
    assert report.error_count == 0
    assert report.evaluate().allowed is True

    empty_src = _map_source()
    empty_src.province_map[:] = 0
    blocked = check_project_readiness_report(_project(), empty_src, context="foundation_candidate")
    assert blocked.error_count == 1
    assert blocked.evaluate().allowed is False
    assert blocked.evaluate("draft_preview").allowed is True
    with pytest.raises(ValueError):
        check_project_readiness_report(_project(), _map_source(), context="no_such_gate")


def test_validate_before_export_report_calls_once_and_preserves_legacy(monkeypatch):
    original = export_service.validate_before_export
    calls = []

    def _fake(canvas, state_mgr, country_mgr, profile=None, game_target=None, dimensions=None):
        calls.append((profile, game_target, dimensions))
        return ["No states; fake"]

    monkeypatch.setattr(export_service, "validate_before_export", _fake)
    canvas = SimpleNamespace(province_map=np.ones((4, 4), dtype=np.int32))
    report = export_service.validate_before_export_report(canvas, StateManager(), CountryManager())
    assert len(calls) == 1
    assert calls[0] == (None, None, None)
    assert isinstance(report, ValidationReport)
    assert report.source == PREFLIGHT_SOURCE
    assert report.context == "draft_preview"
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.layer == PREFLIGHT_LAYER
    assert finding.code == "preflight.states"
    assert finding.message == "No states; fake"
    monkeypatch.undo()

    class _EmptyCanvas:
        province_map = np.zeros((10, 10), dtype=np.int32)

    legacy = validate_before_export(_EmptyCanvas(), StateManager(), CountryManager())
    assert legacy == ["No province data; generate provinces first"]
    mirrored = export_service.validate_before_export_report(_EmptyCanvas(), StateManager(), CountryManager())
    assert [item.message for item in mirrored.findings] == legacy
    assert [item.code for item in mirrored.findings] == ["preflight.provinces"]


def test_preflight_codes_are_stable_categories():
    cases = {
        "No province data; generate provinces first": "preflight.provinces",
        "3 states have no country: 1, 2, 5...": "preflight.countries",
        "Country TST has no capital": "preflight.countries",
        "2 states have no owner and no country is available for assignment": "preflight.countries",
        "5 land provinces are not assigned to a state (assigned automatically during export)": "preflight.states",
        "No states; group provinces automatically or create a state manually": "preflight.states",
        "Map width 100 is not a multiple of 64": "preflight.map_dimensions",
        "Explicit export dimensions 100x100 do not match map arrays 4x4": "preflight.map_dimensions",
        "River: something odd at the source": "preflight.rivers",
        "No continents are defined; the default continent will be used during export": "preflight.continents",
        "2 states contain exclaves and cannot fit in one strategic region": "preflight.strategic_regions",
        "some totally unrelated message": "preflight.check",
    }
    for message, expected in cases.items():
        assert preflight_message_code(message) == expected
    for message in cases:
        assert not any(char.isdigit() for char in preflight_message_code(message))
    messages = list(cases)
    snapshot = list(messages)
    first = report_from_preflight_messages(messages)
    assert messages == snapshot
    assert first.source == PREFLIGHT_SOURCE
    assert [item.code for item in first.findings] == [cases[message] for message in messages]
    assert all(item.layer == PREFLIGHT_LAYER for item in first.findings)
    assert all(item.severity == "warning" for item in first.findings)
    assert report_from_preflight_messages(messages).to_dict() == first.to_dict()
    assert report_from_preflight_messages([]).total == 0
    assert report_from_preflight_messages(None).total == 0
    with pytest.raises(ValueError):
        report_from_preflight_messages(["   "])
    from services.validation_service import finding_from_preflight_message
    with pytest.raises(ValueError):
        finding_from_preflight_message("note", severity="fatal")


def _orphan_fixture():
    pm = np.ones((6, 6), dtype=np.int32)
    pm[:, 3:] = 2
    tm = np.full((6, 6), TILE_LAND, dtype=np.uint8)
    state_mgr = StateManager()
    state_mgr.create_state([1])
    country_mgr = CountryManager()
    country_mgr.create_country("AAA", "Test", (100, 100, 100))
    return tm, pm, state_mgr, country_mgr


def test_pre_export_populates_report_without_mutation():
    tm, pm, state_mgr, country_mgr = _orphan_fixture()
    report = pre_export_check_and_fix(tm, pm, None, state_mgr, country_mgr)
    assert all(isinstance(text, str) for text in report.warnings)
    assert all(isinstance(text, str) for text in report.fixed)
    assert set(report.stats) == {"provinces", "states", "countries"}
    assert isinstance(report.validation_report, ValidationReport)
    assert report.validation_report.source == PREFLIGHT_SOURCE
    assert [item.message for item in report.validation_report.findings] == list(report.warnings)
    assert all(item.layer == PREFLIGHT_LAYER for item in report.validation_report.findings)
    assert any(item.code == "preflight.states" for item in report.validation_report.findings)

    before = list(report.warnings)
    report_from_preflight_messages(report.warnings)
    assert list(report.warnings) == before

    tm2, pm2, state_mgr2, country_mgr2 = _orphan_fixture()
    repeat = pre_export_check_and_fix(tm2, pm2, None, state_mgr2, country_mgr2)
    assert repeat.validation_report.to_dict() == report.validation_report.to_dict()

    empty_pm = np.zeros((6, 6), dtype=np.int32)
    empty_tm = np.full((6, 6), TILE_SEA, dtype=np.uint8)
    early = pre_export_check_and_fix(empty_tm, empty_pm, None, StateManager(), CountryManager())
    assert early.warnings == ["No province data"]
    assert [item.code for item in early.validation_report.findings] == ["preflight.provinces"]


def test_export_report_compat_and_preserved_through_export_mod(monkeypatch):
    legacy = ExportReport(["warn"], ["fix"], {"provinces": 1})
    assert legacy.validation_report is None
    assert legacy.warnings == ["warn"] and legacy.fixed == ["fix"]

    from export import mod_exporter

    def _fake_export(tile_map, province_map, output_dir, **kwargs):
        os.makedirs(output_dir, exist_ok=True)

    monkeypatch.setattr(mod_exporter, "export_full_mod", _fake_export)
    scratch = Path("tmp/m3-2b-test-tmp") / uuid.uuid4().hex[:8]
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        source = _map_source()
        canvas = SimpleNamespace(
            tile_map=source.tile_map, province_map=source.province_map,
            terrain_map=source.terrain_map, height_map=source.height_map,
            river_map=np.full(source.tile_map.shape, 255, dtype=np.uint8),
            map_data=SimpleNamespace(provincial_terrain={}),
        )
        project = _project()
        result = export_service.export_mod(
            str(scratch), canvas, project.state_mgr, project.country_mgr,
            project.continent_mgr, strategic_region_mgr=None,
        )
        assert isinstance(result.validation_report, ValidationReport)
        assert [item.message for item in result.validation_report.findings] == list(result.warnings)
        assert all(item.layer == PREFLIGHT_LAYER for item in result.validation_report.findings)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)