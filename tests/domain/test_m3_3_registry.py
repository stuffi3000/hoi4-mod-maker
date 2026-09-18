"""M3.3 central foundation registry tests (no game install)."""
from __future__ import annotations

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.validation import ValidationFinding, ValidationReport
from domain.validators import (
    FOUNDATION_GEOGRAPHY_VALIDATOR_NAME,
    FOUNDATION_LOGISTICS_VALIDATOR_NAME,
    FOUNDATION_RASTER_VALIDATOR_NAME,
    FOUNDATION_TERRAIN_VALIDATOR_NAME,
    create_foundation_validator_registry,
    run_foundation_validation,
)

pytestmark = pytest.mark.unit

_PLAINS = int(TERRAIN_PALETTE_INDEX["plains"])
_OCEAN = int(TERRAIN_PALETTE_INDEX["ocean"])


def _clean_foundation():
    tile = np.ones((4, 4), dtype=np.uint8) * TILE_LAND
    tile[:, 2:] = TILE_SEA
    province = np.array(
        [[1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2]],
        dtype=np.int32,
    )
    definitions = {1: "land", 2: "sea"}
    terrain = np.full((4, 4), _PLAINS, dtype=np.uint8)
    terrain[:, 2:] = _OCEAN
    river = np.full((4, 4), 255, dtype=np.uint8)
    height = np.full((4, 4), 120, dtype=np.uint8)
    city = np.zeros((4, 4), dtype=np.uint8)
    tree = np.zeros((4, 4), dtype=np.uint8)
    return {
        "tile_map": tile,
        "province_map": province,
        "definitions": definitions,
        "terrain_map": terrain,
        "river_map": river,
        "height_map": height,
        "city_map": city,
        "tree_map": tree,
        "wrap_horizontal": False,
        "max_bbox_ratio": 1.0,
    }


def _clean_managers():
    from domain.managers.adjacency import AdjacencyManager
    from domain.managers.adjacency_rule import AdjacencyRuleManager
    from domain.managers.continent import ContinentManager
    from domain.managers.country import CountryManager
    from domain.managers.railway import RailwayManager
    from domain.managers.state import StateManager
    from domain.managers.strategic_region import StrategicRegionManager
    from domain.managers.supply_node import SupplyNodeManager

    state_mgr = StateManager()
    state_mgr.create_state([1])
    strategic_region_mgr = StrategicRegionManager()
    region = strategic_region_mgr.create_region()
    region.province_ids = [1, 2]
    continent_mgr = ContinentManager()
    country_mgr = CountryManager()
    country_mgr.create_country("AAA", allow_vanilla_tag=True)
    country_mgr.assign_state(1, "AAA")
    country_mgr.set_capital("AAA", 1)
    return {
        "state_mgr": state_mgr,
        "country_mgr": country_mgr,
        "continent_mgr": continent_mgr,
        "strategic_region_mgr": strategic_region_mgr,
        "adjacency_mgr": AdjacencyManager(),
        "railway_mgr": RailwayManager(),
        "supply_mgr": SupplyNodeManager(),
        "adjacency_rule_mgr": AdjacencyRuleManager(),
    }


def _clean_foundation_with_managers():
    inputs = _clean_foundation()
    inputs.update(_clean_managers())
    return inputs


def test_registry_has_exactly_four_deterministic_entries():
    registry = create_foundation_validator_registry()
    assert len(registry) == 4
    assert registry.names == tuple(sorted(registry.names))
    assert registry.names == (
        FOUNDATION_GEOGRAPHY_VALIDATOR_NAME,
        FOUNDATION_LOGISTICS_VALIDATOR_NAME,
        FOUNDATION_RASTER_VALIDATOR_NAME,
        FOUNDATION_TERRAIN_VALIDATOR_NAME,
    )


def test_registry_names_are_stable():
    assert FOUNDATION_RASTER_VALIDATOR_NAME == "raster/definition"
    assert FOUNDATION_TERRAIN_VALIDATOR_NAME == "terrain/layers"
    assert FOUNDATION_GEOGRAPHY_VALIDATOR_NAME == "geography/references"
    assert FOUNDATION_LOGISTICS_VALIDATOR_NAME == "logistics/references"
    first = create_foundation_validator_registry().names
    second = create_foundation_validator_registry().names
    assert first == second


def test_clean_foundation_has_no_findings():
    inputs = _clean_foundation()
    registry = create_foundation_validator_registry()
    assert registry.run(**inputs) == []
    report = run_foundation_validation(**inputs)
    assert isinstance(report, ValidationReport)
    assert report.findings == ()
    assert report.total == 0


def test_clean_managers_fixture_has_no_findings():
    inputs = _clean_foundation_with_managers()
    registry = create_foundation_validator_registry()
    assert registry.run(**inputs) == []
    report = run_foundation_validation(**inputs)
    assert isinstance(report, ValidationReport)
    assert report.findings == ()
    assert report.total == 0


def test_geography_wrapper_flags_missing_state():
    from domain.managers.state import StateManager

    inputs = _clean_foundation_with_managers()
    bad_states = StateManager()
    bad_states.create_state([2])
    inputs["state_mgr"] = bad_states
    registry = create_foundation_validator_registry()
    findings = registry.run(**inputs)
    codes = [item.code for item in findings]
    assert "geography.state_membership" in codes
    report = run_foundation_validation(**inputs)
    assert any(item.code == "geography.state_membership" for item in report)


def test_logistics_wrapper_flags_bad_adjacency():
    from domain.managers.adjacency import AdjacencyEntry, AdjacencyManager

    inputs = _clean_foundation_with_managers()
    bad_adj = AdjacencyManager()
    bad_adj.add(AdjacencyEntry(1, 99, "sea"))
    inputs["adjacency_mgr"] = bad_adj
    registry = create_foundation_validator_registry()
    findings = registry.run(**inputs)
    codes = [item.code for item in findings]
    assert "logistics.adjacency_endpoint" in codes
    report = run_foundation_validation(**inputs)
    assert any(item.code == "logistics.adjacency_endpoint" for item in report)


def test_common_api_runs_both_validators():
    inputs = _clean_foundation()
    inputs["definitions"] = {1: "land"}
    bad_terrain = inputs["terrain_map"].copy()
    bad_terrain[0, 0] = 99
    inputs["terrain_map"] = bad_terrain
    registry = create_foundation_validator_registry()
    findings = registry.run(**inputs)
    codes = [item.code for item in findings]
    assert "raster.definition_missing" in codes
    assert "terrain.index" in codes
    assert all(isinstance(item, ValidationFinding) for item in findings)


def test_raster_and_terrain_findings_keep_registry_order():
    inputs = _clean_foundation()
    inputs["definitions"] = {1: "land"}
    bad_terrain = inputs["terrain_map"].copy()
    bad_terrain[0, 0] = 99
    inputs["terrain_map"] = bad_terrain
    registry = create_foundation_validator_registry()
    findings = registry.run(**inputs)
    codes = [item.code for item in findings]
    raster_pos = codes.index("raster.definition_missing")
    terrain_pos = codes.index("terrain.index")
    assert raster_pos < terrain_pos


def test_all_four_validators_keep_registry_order():
    from domain.managers.adjacency import AdjacencyEntry, AdjacencyManager
    from domain.managers.state import StateManager

    inputs = _clean_foundation_with_managers()
    inputs["definitions"] = {1: "land"}
    bad_terrain = inputs["terrain_map"].copy()
    bad_terrain[0, 0] = 99
    inputs["terrain_map"] = bad_terrain
    bad_states = StateManager()
    bad_states.create_state([2])
    inputs["state_mgr"] = bad_states
    bad_adj = AdjacencyManager()
    bad_adj.add(AdjacencyEntry(1, 99, "sea"))
    inputs["adjacency_mgr"] = bad_adj
    registry = create_foundation_validator_registry()
    findings = registry.run(**inputs)
    codes = [item.code for item in findings]
    assert codes == [
        "geography.state_membership",
        "logistics.adjacency_endpoint",
        "raster.definition_missing",
        "terrain.index",
    ]


def test_run_foundation_validation_report_metadata():
    inputs = _clean_foundation()
    inputs["definitions"] = {1: "land"}
    report = run_foundation_validation(**inputs)
    assert isinstance(report, ValidationReport)
    assert report.context == "draft_preview"
    assert report.source == "foundation"
    assert len(report.findings) >= 1
    assert any(item.code == "raster.definition_missing" for item in report)


def test_run_foundation_validation_custom_context_source():
    inputs = _clean_foundation()
    report = run_foundation_validation(
        **inputs, context="foundation_candidate", source="unit-test"
    )
    assert report.context == "foundation_candidate"
    assert report.source == "unit-test"


def test_run_foundation_validation_forwards_managers():
    from domain.managers.adjacency import AdjacencyEntry, AdjacencyManager

    inputs = _clean_foundation_with_managers()
    assert run_foundation_validation(**inputs).total == 0
    bad_adj = AdjacencyManager()
    bad_adj.add(AdjacencyEntry(1, 99, "sea"))
    inputs["adjacency_mgr"] = bad_adj
    direct = create_foundation_validator_registry().run(**inputs)
    report = run_foundation_validation(**inputs)
    assert [item.code for item in direct] == [item.code for item in report]
    assert any(item.code == "logistics.adjacency_endpoint" for item in report)


def test_wrappers_accept_all_common_kwargs():
    inputs = _clean_foundation()
    full = dict(inputs)
    full.update(
        {
            "profile": None,
            "expected_dimensions": None,
            "include_engine_boundary": False,
            "mixed_threshold": 0.0,
            "terrain_indices": None,
        }
    )
    registry = create_foundation_validator_registry()
    assert registry.run(**full) == []
    report = run_foundation_validation(**full)
    assert report.total == 0


def test_wrappers_accept_all_common_kwargs_with_managers():
    full = _clean_foundation_with_managers()
    full.update(
        {
            "profile": None,
            "expected_dimensions": None,
            "include_engine_boundary": False,
            "mixed_threshold": 0.0,
            "terrain_indices": None,
        }
    )
    registry = create_foundation_validator_registry()
    assert registry.run(**full) == []
    report = run_foundation_validation(**full)
    assert report.total == 0


def test_deterministic_repeatability():
    inputs = _clean_foundation()
    inputs["definitions"] = {1: "land"}
    bad_terrain = inputs["terrain_map"].copy()
    bad_terrain[0, 0] = 99
    inputs["terrain_map"] = bad_terrain
    registry = create_foundation_validator_registry()
    first = registry.run(**inputs)
    second = registry.run(**inputs)
    assert first == second
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    first_report = run_foundation_validation(**inputs)
    second_report = run_foundation_validation(**inputs)
    assert first_report == second_report
    assert first_report.to_dict() == second_report.to_dict()


def test_no_input_mutation():
    inputs = _clean_foundation()
    snapshots = {}
    for key, value in inputs.items():
        if isinstance(value, np.ndarray):
            snapshots[key] = value.copy()
        elif isinstance(value, dict):
            snapshots[key] = dict(value)
        else:
            snapshots[key] = value
    registry = create_foundation_validator_registry()
    registry.run(**inputs)
    run_foundation_validation(**inputs)
    for key, value in inputs.items():
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(value, snapshots[key])
        else:
            assert value == snapshots[key]


def test_exports_preserve_shared_contract():
    import domain.validators as package

    for name in (
        "FINDING_SEVERITIES",
        "GATE_CONTEXTS",
        "SEVERITY_RANK",
        "FOUNDATION_RASTER_VALIDATOR_NAME",
        "FOUNDATION_TERRAIN_VALIDATOR_NAME",
        "FOUNDATION_GEOGRAPHY_VALIDATOR_NAME",
        "FOUNDATION_LOGISTICS_VALIDATOR_NAME",
        "GateDecision",
        "ValidationFinding",
        "ValidationReport",
        "ValidatorRegistry",
        "coerce_finding",
        "evaluate_gate",
        "create_foundation_validator_registry",
        "run_foundation_validation",
    ):
        assert name in package.__all__
        assert hasattr(package, name)
