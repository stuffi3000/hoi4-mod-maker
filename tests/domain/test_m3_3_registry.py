"""M3.3 central foundation registry tests (no game install)."""
from __future__ import annotations

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.validation import ValidationFinding, ValidationReport
from domain.validators import (
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


def test_registry_has_exactly_two_deterministic_entries():
    registry = create_foundation_validator_registry()
    assert len(registry) == 2
    assert registry.names == tuple(sorted(registry.names))
    assert registry.names == (
        FOUNDATION_RASTER_VALIDATOR_NAME,
        FOUNDATION_TERRAIN_VALIDATOR_NAME,
    )


def test_registry_names_are_stable():
    assert FOUNDATION_RASTER_VALIDATOR_NAME == "raster/definition"
    assert FOUNDATION_TERRAIN_VALIDATOR_NAME == "terrain/layers"
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