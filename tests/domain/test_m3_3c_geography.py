"""M3.3c geography and reference validation tests (no game install)."""
from __future__ import annotations

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from domain.validation import ValidationFinding
from domain.validators.geography import CODES, validate_geography_references

pytestmark = pytest.mark.unit

_STABLE_CODES = (
    "geography.state_membership",
    "geography.state_reference",
    "geography.duplicate_membership",
    "geography.region_coverage",
    "geography.region_reference",
    "geography.continent_reference",
    "geography.country_reference",
)


def _codes(findings):
    return [f.code for f in findings]


def _clean_world():
    tile = np.full((4, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array(
        [[1, 1, 2, 2], [1, 1, 2, 2], [3, 3, 4, 4], [3, 3, 4, 4]],
        dtype=np.int32,
    )
    from domain.managers.state import StateManager
    from domain.managers.strategic_region import StrategicRegionManager
    from domain.managers.continent import ContinentManager
    from domain.managers.country import CountryManager
    sm = StateManager()
    sm.create_state([1, 2])
    sm.create_state([3, 4])
    rm = StrategicRegionManager()
    region = rm.create_region()
    region.province_ids = [1, 2, 3, 4]
    cm = ContinentManager()
    com = CountryManager()
    com.create_country("AAA", allow_vanilla_tag=True)
    com.assign_state(1, "AAA")
    com.assign_state(2, "AAA")
    com.set_capital("AAA", 1)
    return tile, prov, sm, rm, cm, com


class _FakeStates:
    def __init__(self, states):
        self.states = states


class _FakeRegions:
    def __init__(self, regions):
        self.regions = regions


def test_stable_codes_match_spec():
    assert tuple(CODES) == _STABLE_CODES
    assert len(set(CODES)) == 7


def test_clean_input_has_no_findings():
    tile, prov, sm, rm, cm, com = _clean_world()
    findings = validate_geography_references(
        prov, tile, state_mgr=sm, strategic_region_mgr=rm, continent_mgr=cm, country_mgr=com
    )
    assert findings == []


def test_clean_state_only_has_no_findings():
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1])
    sm.create_state([2])
    assert validate_geography_references(prov, tile, state_mgr=sm) == []


def test_missing_land_province_is_state_membership_error():
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1])
    findings = validate_geography_references(prov, tile, state_mgr=sm)
    assert len(findings) == 1
    item = findings[0]
    assert item.code == "geography.state_membership"
    assert item.severity == "error"
    assert item.layer == "states"
    assert tuple(item.affected_ids) == (2,)
    assert len(item.coordinates) == 1
    assert "2" in item.evidence


def test_sea_provinces_do_not_require_states():
    tile = np.array(
        [[int(TILE_LAND), int(TILE_LAND), int(TILE_SEA), int(TILE_SEA)], [int(TILE_LAND), int(TILE_LAND), int(TILE_SEA), int(TILE_SEA)]],
        dtype=np.uint8,
    )
    prov = np.array([[1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1])
    assert validate_geography_references(prov, tile, state_mgr=sm) == []
def test_state_reference_reports_dangling_and_invalid():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    fake = _FakeStates({1: [1, 2, 99], 2: [0, -3]})
    findings = validate_geography_references(prov, tile, state_mgr=fake)
    by_code = [f for f in findings if f.code == "geography.state_reference"]
    assert len(by_code) == 1
    item = by_code[0]
    assert item.severity == "error"
    assert 99 in tuple(item.affected_ids)
    assert "unknown_province_refs" in item.evidence


def test_state_id_gaps_are_reported():
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    fake = _FakeStates({1: [1], 3: [2]})
    findings = validate_geography_references(prov, tile, state_mgr=fake)
    ref = [f for f in findings if f.code == "geography.state_reference"]
    assert ref
    assert 2 in tuple(ref[0].affected_ids)
    assert "missing_state_ids" in ref[0].evidence


def test_empty_state_is_reported():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    fake = _FakeStates({1: [1, 2], 2: []})
    findings = validate_geography_references(prov, tile, state_mgr=fake)
    ref = [f for f in findings if f.code == "geography.state_reference"]
    assert ref
    assert 2 in tuple(ref[0].affected_ids)
    assert "empty_states" in ref[0].evidence


def test_duplicate_state_membership_is_error():
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 1, 2, 2], [3, 3, 4, 4]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1, 2])
    sm.create_state([2, 3, 4])
    findings = validate_geography_references(prov, tile, state_mgr=sm)
    dups = [f for f in findings if f.code == "geography.duplicate_membership"]
    assert len(dups) == 1
    assert tuple(dups[0].affected_ids) == (2,)
    assert dups[0].severity == "error"
    assert dups[0].layer == "states"


def test_duplicate_inside_single_state_is_reported():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    fake = _FakeStates({1: [1, 1, 2]})
    findings = validate_geography_references(prov, tile, state_mgr=fake)
    dups = [f for f in findings if f.code == "geography.duplicate_membership"]
    assert dups
    assert 1 in tuple(dups[0].affected_ids)


def test_region_coverage_uncovered_is_warning():
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    from domain.managers.state import StateManager
    from domain.managers.strategic_region import StrategicRegionManager
    sm = StateManager()
    sm.create_state([1, 2])
    rm = StrategicRegionManager()
    region = rm.create_region()
    region.province_ids = [1]
    findings = validate_geography_references(prov, tile, state_mgr=sm, strategic_region_mgr=rm)
    cov = [f for f in findings if f.code == "geography.region_coverage"]
    assert len(cov) == 1
    assert tuple(cov[0].affected_ids) == (2,)
    assert cov[0].severity == "warning"
    assert cov[0].waivable is True


def test_region_reference_dangling_is_error():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    fake_regions = _FakeRegions({1: [1, 2, 77]})
    findings = validate_geography_references(prov, tile, strategic_region_mgr=fake_regions)
    ref = [f for f in findings if f.code == "geography.region_reference"]
    assert ref
    assert 77 in tuple(ref[0].affected_ids)
    assert ref[0].severity == "error"


def test_duplicate_region_membership_is_error():
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 1, 2, 2], [3, 3, 4, 4]], dtype=np.int32)
    fake_regions = _FakeRegions({1: [1, 2], 2: [2, 3, 4]})
    findings = validate_geography_references(prov, tile, strategic_region_mgr=fake_regions)
    dups = [f for f in findings if f.code == "geography.duplicate_membership"]
    assert dups
    assert 2 in tuple(dups[0].affected_ids)
    assert dups[0].severity == "error"
def test_disconnected_state_is_reported():
    tile = np.full((2, 6), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 1, 2, 2, 3, 3], [1, 1, 2, 2, 3, 3]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1, 3])
    sm.create_state([2])
    findings = validate_geography_references(prov, tile, state_mgr=sm, wrap_horizontal=False)
    members = [f for f in findings if f.code == "geography.state_membership"]
    assert any(1 in tuple(f.affected_ids) for f in members)
    assert all(f.severity == "error" for f in members)


def test_disconnected_region_is_warning():
    tile = np.full((2, 6), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 1, 2, 2, 3, 3], [1, 1, 2, 2, 3, 3]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1])
    sm.create_state([2])
    sm.create_state([3])
    fake_regions = _FakeRegions({1: [1, 3], 2: [2]})
    findings = validate_geography_references(prov, tile, state_mgr=sm, strategic_region_mgr=fake_regions, wrap_horizontal=False)
    cov = [f for f in findings if f.code == "geography.region_coverage"]
    assert any(1 in tuple(f.affected_ids) for f in cov)
    assert all(f.severity == "warning" for f in cov)


def test_continent_reference_reports_bad_index_and_dangling():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    from domain.managers.continent import ContinentManager
    cm = ContinentManager()
    cm._province_continent[1] = 5
    cm._province_continent[99] = 0
    findings = validate_geography_references(prov, tile, continent_mgr=cm)
    ref = [f for f in findings if f.code == "geography.continent_reference"]
    assert len(ref) == 1
    assert set(ref[0].affected_ids) == {1, 99}
    assert ref[0].severity == "error"
    assert "out_of_range" in ref[0].evidence
    assert "unknown_province_refs" in ref[0].evidence


def test_country_reference_reports_unknowns_and_capital():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    from domain.managers.state import StateManager
    from domain.managers.country import CountryManager
    sm = StateManager()
    sm.create_state([1, 2])
    com = CountryManager()
    com.create_country("AAA", allow_vanilla_tag=True)
    com._state_owner[99] = "AAA"
    com._state_owner[1] = "ZZZ"
    com.set_capital("AAA", 99)
    findings = validate_geography_references(prov, tile, state_mgr=sm, country_mgr=com)
    ref = [f for f in findings if f.code == "geography.country_reference"]
    assert len(ref) == 1
    assert 99 in tuple(ref[0].affected_ids)
    assert "unknown_state_refs" in ref[0].evidence
    assert "unknown_country_tags" in ref[0].evidence
    assert ref[0].severity == "error"


def test_country_capital_state_mismatch_is_reported():
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    from domain.managers.state import StateManager
    from domain.managers.country import CountryManager
    sm = StateManager()
    sm.create_state([1])
    sm.create_state([2])
    com = CountryManager()
    com.create_country("AAA", allow_vanilla_tag=True)
    com.create_country("BBB", allow_vanilla_tag=True)
    com.assign_state(1, "AAA")
    com.assign_state(2, "BBB")
    com.set_capital("AAA", 2)
    findings = validate_geography_references(prov, tile, state_mgr=sm, country_mgr=com)
    ref = [f for f in findings if f.code == "geography.country_reference"]
    assert ref
    assert 2 in tuple(ref[0].affected_ids)
    assert "capital_state_mismatch" in ref[0].evidence


def test_findings_use_stable_metadata():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    fake = _FakeStates({1: [99]})
    findings = validate_geography_references(prov, tile, state_mgr=fake)
    assert findings
    for item in findings:
        assert isinstance(item, ValidationFinding)
        assert item.code in _STABLE_CODES
        assert item.severity in ("error", "warning")
        assert item.code.startswith("geography.")


def test_region_coverage_warnings_are_waivable_errors_are_not():
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    from domain.managers.state import StateManager
    from domain.managers.strategic_region import StrategicRegionManager
    sm = StateManager()
    sm.create_state([1])
    rm = StrategicRegionManager()
    region = rm.create_region()
    region.province_ids = [1]
    findings = validate_geography_references(prov, tile, state_mgr=sm, strategic_region_mgr=rm)
    for item in findings:
        if item.code == "geography.region_coverage":
            assert item.severity == "warning"
            assert item.waivable is True
        else:
            assert item.severity == "error"
            assert item.waivable is False


def test_output_is_deterministic_and_ordered():
    tile, prov, sm, rm, cm, com = _clean_world()
    first = validate_geography_references(prov, tile, state_mgr=sm, strategic_region_mgr=rm, continent_mgr=cm, country_mgr=com)
    second = validate_geography_references(prov, tile, state_mgr=sm, strategic_region_mgr=rm, continent_mgr=cm, country_mgr=com)
    assert first == second
    tile2 = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov2 = np.array([[1, 1, 2, 2], [3, 3, 4, 4]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm2 = StateManager()
    sm2.create_state([99])
    fake_regions = _FakeRegions({1: [1, 77], 1 - 1 + 1: [1, 2]})
    run_a = validate_geography_references(prov2, tile2, state_mgr=sm2, strategic_region_mgr=fake_regions)
    run_b = validate_geography_references(prov2, tile2, state_mgr=sm2, strategic_region_mgr=fake_regions)
    assert [f.code for f in run_a] == [f.code for f in run_b]
    assert [tuple(f.affected_ids) for f in run_a] == [tuple(f.affected_ids) for f in run_b]
    order = {code: index for index, code in enumerate(_STABLE_CODES)}
    positions = [order[code] for code in [f.code for f in run_a]]
    assert positions == sorted(positions)


def test_inputs_are_not_mutated():
    tile, prov, sm, rm, cm, com = _clean_world()
    tile_before = tile.copy()
    prov_before = prov.copy()
    states_before = {sid: list(state.provinces) for sid, state in sm.states.items()}
    regions_before = {rid: list(region.province_ids) for rid, region in rm.regions.items()}
    validate_geography_references(prov, tile, state_mgr=sm, strategic_region_mgr=rm, continent_mgr=cm, country_mgr=com)
    np.testing.assert_array_equal(tile, tile_before)
    np.testing.assert_array_equal(prov, prov_before)
    assert {sid: list(state.provinces) for sid, state in sm.states.items()} == states_before
    assert {rid: list(region.province_ids) for rid, region in rm.regions.items()} == regions_before


def test_invalid_province_map_returns_error_without_raising():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    bad = np.ones((2,), dtype=np.int32)
    findings = validate_geography_references(bad, tile)
    assert len(findings) == 1
    assert findings[0].code == "geography.state_reference"
    assert findings[0].severity == "error"
    none_findings = validate_geography_references(None, tile)
    assert none_findings and none_findings[0].code == "geography.state_reference"


def test_mismatched_tile_shape_falls_back_without_crashing():
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    tile = np.full((4, 4), int(TILE_LAND), dtype=np.uint8)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1, 2])
    assert validate_geography_references(prov, tile, state_mgr=sm) == []
def test_wrap_horizontal_contract_connects_across_seam():
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2, 3, 1], [1, 2, 3, 1]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1, 3])
    sm.create_state([2])
    wrapped = validate_geography_references(prov, tile, state_mgr=sm)
    assert not [f for f in wrapped if f.code == "geography.state_membership" and 1 in tuple(f.affected_ids)]
    unwrapped = validate_geography_references(prov, tile, state_mgr=sm, wrap_horizontal=False)
    members = [f for f in unwrapped if f.code == "geography.state_membership"]
    assert any(1 in tuple(f.affected_ids) for f in members)
    assert all(f.severity == "error" for f in members)


def test_wrap_explicit_overrides_profile():
    from types import SimpleNamespace
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2, 3, 1], [1, 2, 3, 1]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1, 3])
    sm.create_state([2])
    no_wrap_profile = SimpleNamespace(dimensions=SimpleNamespace(wrap_horizontal=False))
    via_profile = validate_geography_references(prov, tile, state_mgr=sm, profile=no_wrap_profile)
    assert any(1 in tuple(f.affected_ids) for f in via_profile if f.code == "geography.state_membership")
    overridden = validate_geography_references(prov, tile, state_mgr=sm, profile=no_wrap_profile, wrap_horizontal=True)
    assert not [f for f in overridden if f.code == "geography.state_membership" and 1 in tuple(f.affected_ids)]
    wrap_profile = SimpleNamespace(dimensions=SimpleNamespace(wrap_horizontal=True))
    via_wrap_profile = validate_geography_references(prov, tile, state_mgr=sm, profile=wrap_profile)
    assert not [f for f in via_wrap_profile if f.code == "geography.state_membership" and 1 in tuple(f.affected_ids)]


def test_region_disconnected_honors_wrap():
    tile = np.full((2, 4), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2, 3, 1], [1, 2, 3, 1]], dtype=np.int32)
    fake_regions = _FakeRegions({1: [1, 3], 2: [2]})
    wrapped = validate_geography_references(prov, tile, strategic_region_mgr=fake_regions)
    assert not [f for f in wrapped if f.code == "geography.region_coverage" and 1 in tuple(f.affected_ids)]
    unwrapped = validate_geography_references(prov, tile, strategic_region_mgr=fake_regions, wrap_horizontal=False)
    cov = [f for f in unwrapped if f.code == "geography.region_coverage"]
    assert any(1 in tuple(f.affected_ids) for f in cov)


def test_state_spanning_multiple_regions_is_state_membership_error():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1, 2])
    fake_regions = _FakeRegions({1: [1], 2: [2]})
    findings = validate_geography_references(prov, tile, state_mgr=sm, strategic_region_mgr=fake_regions)
    cross = [f for f in findings if f.code == "geography.state_membership" and "cross_region_states" in (f.evidence or "")]
    assert len(cross) == 1
    item = cross[0]
    assert item.severity == "error"
    assert item.layer == "states"
    assert tuple(item.affected_ids) == (1,)
    assert len(item.coordinates) == 1
    assert "1" in item.evidence and "2" in item.evidence
    assert "regions" in item.evidence


def test_state_spanning_ignores_dangling_references():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    fake_states = _FakeStates({1: [1, 99]})
    fake_regions = _FakeRegions({1: [1], 2: [2]})
    findings = validate_geography_references(prov, tile, state_mgr=fake_states, strategic_region_mgr=fake_regions)
    cross = [f for f in findings if f.code == "geography.state_membership" and "cross_region_states" in (f.evidence or "")]
    assert cross == []
    assert any(f.code == "geography.state_reference" for f in findings)


def test_state_spanning_requires_both_lookups():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, 2], [1, 2]], dtype=np.int32)
    from domain.managers.state import StateManager
    sm = StateManager()
    sm.create_state([1, 2])
    findings = validate_geography_references(prov, tile, state_mgr=sm)
    cross = [f for f in findings if f.code == "geography.state_membership" and "cross_region_states" in (f.evidence or "")]
    assert cross == []


def test_malformed_object_province_map_returns_typed_finding():
    tile = np.full((2, 2), int(TILE_LAND), dtype=np.uint8)
    prov = np.array([[1, {"id": 2}], [3, 4]], dtype=object)
    fake = _FakeStates({1: [1, 3, 4]})
    findings = validate_geography_references(prov, tile, state_mgr=fake)
    assert findings
    assert all(isinstance(f, ValidationFinding) for f in findings)
    ref = [f for f in findings if f.code == "geography.state_reference"]
    assert ref
    assert any("unparseable_province_ids" in (f.evidence or "") for f in ref)
