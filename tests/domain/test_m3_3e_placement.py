"""M3.3e placement validation slice tests (no game install)."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from domain.validation import FINDING_SEVERITIES, ValidationFinding
from domain.validators.placement import CODES, validate_placement_references

pytestmark = pytest.mark.unit


@dataclass
class _Placed:
    province_id: int | None = None
    state_id: int | None = None
    building_type: str | None = None
    x: float | None = None
    y: float | None = None
    sea_province: int | None = None
    provenance: str | None = None


def _land_2x3():
    tile = np.full((2, 3), TILE_LAND, dtype=np.uint8)
    prov = np.array([[1, 2, 3], [1, 2, 3]], dtype=np.int32)
    return tile, prov


def _coast_2x4():
    tile = np.array(
        [[TILE_LAND, TILE_LAND, TILE_SEA, TILE_SEA],
         [TILE_LAND, TILE_LAND, TILE_SEA, TILE_SEA]],
        dtype=np.uint8,
    )
    prov = np.array([[1, 1, 2, 2], [3, 3, 4, 4]], dtype=np.int32)
    return tile, prov


def _codes(findings):
    return [item.code for item in findings]


def _by_code(findings):
    grouped = {}
    for item in findings:
        grouped.setdefault(item.code, []).append(item)
    return grouped


def _state_mgr_two():
    from domain.managers.state import StateManager

    mgr = StateManager()
    mgr.create_state([1, 2])
    mgr.create_state([3])
    return mgr


def _region_mgr_all(pids):
    from domain.managers.strategic_region import StrategicRegionManager

    mgr = StrategicRegionManager()
    region = mgr.create_region()
    region.province_ids = list(pids)
    return mgr


def test_clean_data_has_no_findings():
    tile, prov = _land_2x3()
    state_mgr = _state_mgr_two()
    region_mgr = _region_mgr_all([1, 2, 3])
    placements = [
        {"province_id": 1, "state_id": 1, "building_type": "bunker", "x": 0.5, "y": 0.5, "provenance": "authored"},
        {"province_id": 2, "state_id": 1, "building_type": "arms_factory", "x": 1.5, "y": 0.5, "provenance": "authored"},
        {"province_id": 3, "state_id": 2, "building_type": "supply_node", "x": 2.5, "y": 1.5, "provenance": "authored"},
    ]
    positions = [
        {"province_id": 1, "x": 0.5, "y": 1.5},
        {"province_id": 3, "x": 2.5, "y": 0.5},
    ]
    weather = [{"region_id": 1, "x": 1.5, "y": 0.5}]
    findings = validate_placement_references(
        prov, tile,
        placement_entries=placements,
        position_entries=positions,
        weather_entries=weather,
        state_mgr=state_mgr,
        strategic_region_mgr=region_mgr,
    )
    assert findings == []


def test_clean_port_and_mixed_record_shapes():
    tile, prov = _coast_2x4()
    from domain.managers.state import StateManager

    state_mgr = StateManager()
    state_mgr.create_state([1, 3])
    state_mgr.create_state([2, 4])
    region_mgr = _region_mgr_all([1, 2, 3, 4])
    port = _Placed(province_id=1, building_type="naval_base_spawn", x=0.5, y=0.5, sea_province=2, provenance="authored")
    dock = {"province_id": 3, "building_type": "dockyard", "x": 0.5, "y": 1.5, "provenance": "authored", "notes": "extra ignored"}
    tuple_pos = {"province_id": 2, "position": (2.5, 0.5)}
    findings = validate_placement_references(
        prov, tile, building_entries=[port, dock], position_entries=[tuple_pos],
        state_mgr=state_mgr, strategic_region_mgr=region_mgr,
    )
    assert findings == []
def test_absent_layers_is_noop():
    tile, prov = _land_2x3()
    assert validate_placement_references(prov, tile) == []
    assert validate_placement_references(prov, tile, placement_entries=[], position_entries=[], building_entries=[], weather_entries=[]) == []
    assert validate_placement_references(None, None) == []
    assert validate_placement_references(None, None, placement_entries=[], weather_entries=[]) == []


def test_out_of_bounds_coordinate_is_error():
    tile, prov = _land_2x3()
    entries = [
        {"province_id": 1, "building_type": "bunker", "x": 99.5, "y": 99.5},
        {"province_id": 2, "x": -1.0, "y": 0.5},
    ]
    findings = validate_placement_references(prov, tile, placement_entries=entries)
    assert _codes(findings) == ["placement.coordinate"]
    item = findings[0]
    assert item.severity == "error"
    assert item.layer == "placement"
    assert "out of bounds" in item.evidence
    assert tuple(item.affected_ids) == (1, 2)


def test_foreign_province_and_state_coordinate():
    tile, prov = _land_2x3()
    state_mgr = _state_mgr_two()
    entries = [{"province_id": 1, "state_id": 1, "building_type": "bunker", "x": 2.5, "y": 0.5}]
    findings = validate_placement_references(prov, tile, placement_entries=entries, state_mgr=state_mgr)
    by_code = _by_code(findings)
    assert "placement.coordinate" in by_code
    coord = by_code["placement.coordinate"][0]
    assert coord.severity == "error"
    assert "resolves to province 3" in coord.evidence
    assert 1 in tuple(coord.affected_ids)
    assert 3 in tuple(coord.affected_ids)


def test_declared_surface_mismatch():
    tile, prov = _coast_2x4()
    entries = [{"province_id": 2, "x": 2.5, "y": 0.5, "surface": "land"}]
    findings = validate_placement_references(prov, tile, position_entries=entries)
    assert _codes(findings) == ["placement.coordinate"]
    assert "declares surface land but resolves to sea" in findings[0].evidence


def test_invalid_building_type_is_error():
    tile, prov = _land_2x3()
    entries = [
        {"province_id": 1, "building_type": "infrastructure", "x": 0.5, "y": 0.5},
        {"province_id": 2, "building_type": "Death Star", "x": 1.5, "y": 0.5},
    ]
    findings = validate_placement_references(prov, tile, building_entries=entries)
    assert _codes(findings) == ["placement.building"]
    item = findings[0]
    assert item.severity == "error"
    assert "illegal building type" in item.evidence
    assert tuple(item.affected_ids) == (1, 2)


def test_unknown_province_and_state_references():
    tile, prov = _land_2x3()
    state_mgr = _state_mgr_two()
    entries = [{"province_id": 99, "state_id": 77, "building_type": "bunker", "x": 0.5, "y": 0.5}]
    findings = validate_placement_references(prov, tile, building_entries=entries, state_mgr=state_mgr)
    by_code = _by_code(findings)
    assert "placement.building" in by_code
    evidence = by_code["placement.building"][0].evidence
    assert "unknown province 99" in evidence
    assert "unknown state 77" in evidence


def test_province_state_mismatch_is_building_error():
    tile, prov = _land_2x3()
    state_mgr = _state_mgr_two()
    entries = [{"province_id": 3, "state_id": 1, "building_type": "bunker", "x": 2.5, "y": 0.5}]
    findings = validate_placement_references(prov, tile, building_entries=entries, state_mgr=state_mgr)
    by_code = _by_code(findings)
    assert "placement.building" in by_code
    assert "declares state 1" in by_code["placement.building"][0].evidence


def test_building_on_water_is_error():
    tile, prov = _coast_2x4()
    entries = [{"province_id": 2, "building_type": "bunker", "x": 2.5, "y": 0.5}]
    findings = validate_placement_references(prov, tile, building_entries=entries)
    assert _codes(findings) == ["placement.building"]
    assert "on water" in findings[0].evidence
def test_port_requires_coastal_province():
    tile, prov = _coast_2x4()
    inland_tile = np.full((2, 3), TILE_LAND, dtype=np.uint8)
    inland_prov = np.array([[1, 2, 3], [1, 2, 3]], dtype=np.int32)
    entries = [{"province_id": 1, "building_type": "naval_base_spawn", "x": 0.5, "y": 0.5, "sea_province": 2}]
    findings = validate_placement_references(inland_prov, inland_tile, building_entries=entries)
    assert _codes(findings) == ["placement.port"]
    assert "non-coastal" in findings[0].evidence
    assert findings[0].severity == "error"


def test_port_missing_and_wrong_sea():
    tile, prov = _coast_2x4()
    missing = [{"province_id": 1, "building_type": "naval_base_spawn", "x": 0.5, "y": 0.5}]
    findings = validate_placement_references(prov, tile, building_entries=missing)
    assert _codes(findings) == ["placement.port"]
    assert "missing its sea connection" in findings[0].evidence
    wrong = [{"province_id": 1, "building_type": "naval_base_spawn", "x": 0.5, "y": 0.5, "sea_province": 4}]
    findings = validate_placement_references(prov, tile, building_entries=wrong)
    assert _codes(findings) == ["placement.port"]
    assert "intended sea is 2" in findings[0].evidence
    land_sea = [{"province_id": 1, "building_type": "naval_base_spawn", "x": 0.5, "y": 0.5, "sea_province": 1}]
    findings = validate_placement_references(prov, tile, building_entries=land_sea)
    assert "surface=land" in _by_code(findings)["placement.port"][0].evidence


def test_port_unknown_sea_without_tile():
    _tile, prov = _land_2x3()
    entries = [{"province_id": 1, "building_type": "naval_base_spawn", "x": 0.5, "y": 0.5, "sea_province": 99}]
    findings = validate_placement_references(prov, None, building_entries=entries)
    assert _codes(findings) == ["placement.port"]
    assert "unknown sea province 99" in findings[0].evidence


def test_duplicate_exact_reports_collision_and_fallback_repeat():
    tile, prov = _land_2x3()
    entries = [
        {"province_id": 1, "building_type": "bunker", "x": 0.5, "y": 0.5, "provenance": "authored"},
        {"province_id": 2, "building_type": "bunker", "x": 0.5, "y": 0.5, "provenance": "authored"},
    ]
    findings = validate_placement_references(prov, tile, placement_entries=entries)
    by_code = _by_code(findings)
    assert "placement.collision" in by_code
    collision = by_code["placement.collision"][0]
    assert collision.severity == "warning"
    assert collision.waivable is True
    assert "duplicate_transform" in collision.evidence
    assert "placement.fallback" in by_code
    assert "repeated_centroid" in by_code["placement.fallback"][0].evidence


def test_near_collision_without_exact_repeat():
    tile, prov = _land_2x3()
    entries = [
        {"province_id": 1, "x": 0.5, "y": 0.5},
        {"province_id": 2, "x": 1.0, "y": 0.5},
    ]
    findings = validate_placement_references(prov, tile, position_entries=entries)
    by_code = _by_code(findings)
    assert "placement.collision" in by_code
    assert "near_collision" in by_code["placement.collision"][0].evidence
    assert "placement.fallback" not in by_code


def test_wrap_aware_collision_distance():
    tile = np.full((1, 3), TILE_LAND, dtype=np.uint8)
    prov = np.array([[1, 2, 3]], dtype=np.int32)
    entries = [
        {"province_id": 1, "x": 0.2, "y": 0.5},
        {"province_id": 3, "x": 2.8, "y": 0.5},
    ]
    wrapped = validate_placement_references(prov, tile, position_entries=entries, wrap_horizontal=True)
    assert "placement.collision" in _by_code(wrapped)
    unwrapped = validate_placement_references(prov, tile, position_entries=entries, wrap_horizontal=False)
    assert "placement.collision" not in _by_code(unwrapped)
    profile = SimpleNamespace(dimensions=SimpleNamespace(wrap_horizontal=False))
    via_profile = validate_placement_references(prov, tile, position_entries=entries, profile=profile)
    assert "placement.collision" not in _by_code(via_profile)
    via_override = validate_placement_references(prov, tile, position_entries=entries, profile=profile, wrap_horizontal=True)
    assert "placement.collision" in _by_code(via_override)


def test_fallback_flag_is_warning_in_draft_and_blocker_when_frozen():
    tile, prov = _land_2x3()
    entries = [{"province_id": 1, "building_type": "bunker", "x": 0.5, "y": 0.5, "provenance": "fallback"}]
    draft = validate_placement_references(prov, tile, placement_entries=entries, lifecycle="draft")
    assert _codes(draft) == ["placement.fallback"]
    assert draft[0].severity == "warning"
    assert draft[0].waivable is True
    frozen = validate_placement_references(prov, tile, placement_entries=entries, lifecycle="frozen")
    assert _codes(frozen) == ["placement.fallback"]
    assert frozen[0].severity == "blocker"
    assert frozen[0].waivable is False
    flagged = [{"province_id": 2, "x": 1.5, "y": 0.5, "is_fallback": True}]
    draft_flag = validate_placement_references(prov, tile, position_entries=flagged, lifecycle="draft")
    assert "fallback" in _by_code(draft_flag)["placement.fallback"][0].evidence
def test_weather_region_containment_and_unknown_region():
    tile, prov = _land_2x3()
    from domain.managers.strategic_region import StrategicRegionManager

    mgr = StrategicRegionManager()
    first = mgr.create_region()
    first.province_ids = [1, 2]
    second = mgr.create_region()
    second.province_ids = [3]
    outside = [{"region_id": 1, "x": 2.5, "y": 0.5}]
    findings = validate_placement_references(prov, tile, weather_entries=outside, strategic_region_mgr=mgr)
    assert _codes(findings) == ["placement.weather"]
    assert "resolves to province 3 in region 2" in findings[0].evidence
    assert findings[0].severity == "error"
    unknown = [{"region_id": 99, "x": 0.5, "y": 0.5}]
    findings = validate_placement_references(prov, tile, weather_entries=unknown, strategic_region_mgr=mgr)
    assert "unknown strategic region 99" in _by_code(findings)["placement.weather"][0].evidence
    missing = [{"region_id": 1}]
    findings = validate_placement_references(prov, tile, weather_entries=missing, strategic_region_mgr=mgr)
    assert "missing or malformed coordinates" in _by_code(findings)["placement.weather"][0].evidence


def test_malformed_records_do_not_raise():
    tile, prov = _land_2x3()
    entries = [None, "bad", 123, {"province_id": 1}, {"x": "oops", "y": None}]
    findings = validate_placement_references(prov, tile, placement_entries=entries)
    by_code = _by_code(findings)
    assert "placement.coordinate" in by_code
    assert "malformed record" in by_code["placement.coordinate"][0].evidence
    assert "missing or malformed coordinates" in by_code["placement.coordinate"][0].evidence
    weather_bad = [None, 42]
    findings = validate_placement_references(prov, tile, weather_entries=weather_bad)
    assert "placement.weather" in _by_code(findings)
    for item in findings:
        assert isinstance(item, ValidationFinding)
        assert item.code in CODES
        assert item.severity in FINDING_SEVERITIES


def test_missing_raster_keeps_structural_checks():
    entries = [
        {"province_id": 1, "building_type": "Nope", "x": 0.5, "y": 0.5},
        {"province_id": 1, "building_type": "bunker", "x": 0.5, "y": 0.5, "provenance": "fallback"},
    ]
    findings = validate_placement_references(None, None, building_entries=entries)
    by_code = _by_code(findings)
    assert "placement.building" in by_code
    assert "illegal building type" in by_code["placement.building"][0].evidence
    assert "placement.fallback" in by_code
    assert "unknown" not in by_code["placement.building"][0].evidence


def test_stable_codes_metadata_and_determinism():
    tile, prov = _coast_2x4()
    state_mgr = _state_mgr_two()
    from domain.managers.strategic_region import StrategicRegionManager

    region_mgr = StrategicRegionManager()
    region = region_mgr.create_region()
    region.province_ids = [1, 2, 3, 4]
    placements = [
        {"province_id": 99, "building_type": "Nope", "x": 99.5, "y": 99.5, "provenance": "fallback", "sea_province": 100},
        {"province_id": 1, "building_type": "naval_base_spawn", "x": 0.5, "y": 0.5, "sea_province": 4},
        {"province_id": 1, "building_type": "bunker", "x": 0.5, "y": 0.5},
        {"province_id": 2, "building_type": "bunker", "x": 0.5, "y": 0.5},
    ]
    weather = [{"region_id": 77, "x": 0.5, "y": 0.5}]
    kwargs = dict(
        placement_entries=placements,
        weather_entries=weather,
        state_mgr=state_mgr,
        strategic_region_mgr=region_mgr,
    )
    first = validate_placement_references(prov, tile, **kwargs)
    second = validate_placement_references(prov, tile, **kwargs)
    assert first == second
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert first
    order = []
    for item in first:
        assert isinstance(item, ValidationFinding)
        assert item.code in CODES
        assert item.code.startswith("placement.")
        assert item.severity in FINDING_SEVERITIES
        assert item.layer == "placement"
        assert item.message.strip()
        assert item.evidence.strip()
        assert tuple(sorted(item.affected_ids)) == tuple(item.affected_ids)
        assert tuple(sorted(item.coordinates)) == tuple(item.coordinates)
        assert len(item.affected_ids) <= 64
        assert len(item.coordinates) <= 8
        order.append(CODES.index(item.code))
    assert order == sorted(order)
    by_code = _by_code(first)
    assert by_code["placement.coordinate"][0].severity == "error"
    assert by_code["placement.building"][0].severity == "error"
    assert by_code["placement.port"][0].severity == "error"
    assert by_code["placement.collision"][0].severity == "warning"
    assert by_code["placement.collision"][0].waivable is True
    assert by_code["placement.fallback"][0].severity == "warning"
    assert by_code["placement.fallback"][0].waivable is True
    assert by_code["placement.weather"][0].severity == "error"


def test_no_input_mutation():
    tile, prov = _land_2x3()
    tile_snapshot = tile.copy()
    prov_snapshot = prov.copy()
    state_mgr = _state_mgr_two()
    region_mgr = _region_mgr_all([1, 2, 3])
    placements = [
        {"province_id": 99, "building_type": "bunker", "x": 0.5, "y": 0.5, "extra": [1, 2]},
        _Placed(province_id=1, building_type="bunker", x=99.5, y=0.5, provenance="authored"),
    ]
    weather = [{"region_id": 1, "x": 0.5, "y": 0.5, "size": "small"}]
    placements_snapshot = copy.deepcopy(placements)
    weather_snapshot = copy.deepcopy(weather)
    state_snapshot = copy.deepcopy(state_mgr.states)
    region_snapshot = copy.deepcopy(region_mgr.regions)
    validate_placement_references(
        prov, tile, placement_entries=placements, weather_entries=weather,
        state_mgr=state_mgr, strategic_region_mgr=region_mgr,
    )
    np.testing.assert_array_equal(tile, tile_snapshot)
    np.testing.assert_array_equal(prov, prov_snapshot)
    assert placements[0] == placements_snapshot[0]
    assert placements[0]["extra"] == [1, 2]
    assert weather == weather_snapshot
    assert state_mgr.states.keys() == state_snapshot.keys()
    assert region_mgr.regions.keys() == region_snapshot.keys()


def test_port_invalid_province_reports_port_finding():
    tile, prov = _coast_2x4()
    missing = [{'building_type': 'naval_base_spawn', 'x': 0.5, 'y': 0.5, 'sea_province': 2}]
    by_code = _by_code(validate_placement_references(prov, tile, building_entries=missing))
    assert 'placement.port' in by_code
    ev = by_code['placement.port'][0].evidence
    assert 'missing' in ev.lower()
    assert 'coastal/sea validation cannot succeed' in ev
    illegal = [{'province_id': 'oops', 'building_type': 'naval_base_spawn', 'x': 0.5, 'y': 0.5, 'sea_province': 2}]
    by_code = _by_code(validate_placement_references(prov, tile, building_entries=illegal))
    assert 'placement.port' in by_code
    ev = by_code['placement.port'][0].evidence
    assert 'illegal' in ev.lower()
    assert 'coastal/sea validation cannot succeed' in ev
    assert 'placement.building' in by_code
    unknown = [{'province_id': 99, 'building_type': 'naval_base_spawn', 'x': 0.5, 'y': 0.5, 'sea_province': 2}]
    by_code = _by_code(validate_placement_references(prov, tile, building_entries=unknown))
    assert 'placement.port' in by_code
    ev = by_code['placement.port'][0].evidence
    assert 'unknown province 99' in ev
    assert 'coastal/sea validation cannot succeed' in ev
    assert 'placement.building' in by_code


def test_near_coordinates_not_exact_duplicate():
    tile, prov = _land_2x3()
    entries = [{'province_id': 1, 'x': 0.5, 'y': 0.5}, {'province_id': 2, 'x': 0.504, 'y': 0.504}]
    by_code = _by_code(validate_placement_references(prov, tile, position_entries=entries))
    assert 'placement.collision' in by_code
    ev = by_code['placement.collision'][0].evidence
    assert 'near_collision' in ev
    assert 'duplicate_transform' not in ev
    if 'placement.fallback' in by_code:
        assert 'repeated_centroid' not in by_code['placement.fallback'][0].evidence
    exact = [{'province_id': 1, 'x': 0.5, 'y': 0.5}, {'province_id': 2, 'x': 0.5, 'y': 0.5}]
    by_code2 = _by_code(validate_placement_references(prov, tile, position_entries=exact))
    assert 'duplicate_transform' in by_code2['placement.collision'][0].evidence
    assert 'repeated_centroid' in by_code2['placement.fallback'][0].evidence


def test_fallback_flag_rejects_arbitrary_strings():
    tile, prov = _land_2x3()
    arbitrary = [{'province_id': 1, 'x': 0.5, 'y': 0.5, 'is_fallback': 'draft'}]
    assert 'placement.fallback' not in _by_code(validate_placement_references(prov, tile, position_entries=arbitrary, lifecycle='draft'))
    explicit_true = [{'province_id': 1, 'x': 0.5, 'y': 0.5, 'is_fallback': True}]
    assert 'placement.fallback' in _by_code(validate_placement_references(prov, tile, position_entries=explicit_true, lifecycle='draft'))
    canonical = [{'province_id': 1, 'x': 0.5, 'y': 0.5, 'is_fallback': 'auto'}]
    assert 'placement.fallback' in _by_code(validate_placement_references(prov, tile, position_entries=canonical, lifecycle='draft'))
    fallback_word = [{'province_id': 1, 'x': 0.5, 'y': 0.5, 'is_fallback': 'fallback'}]
    assert 'placement.fallback' in _by_code(validate_placement_references(prov, tile, position_entries=fallback_word, lifecycle='draft'))
    yes_flag = [{'province_id': 1, 'x': 0.5, 'y': 0.5, 'is_fallback': 'yes'}]
    assert 'placement.fallback' in _by_code(validate_placement_references(prov, tile, position_entries=yes_flag, lifecycle='draft'))
    authored = [{'province_id': 1, 'x': 0.5, 'y': 0.5, 'is_fallback': 'authored'}]
    assert 'placement.fallback' not in _by_code(validate_placement_references(prov, tile, position_entries=authored, lifecycle='draft'))
