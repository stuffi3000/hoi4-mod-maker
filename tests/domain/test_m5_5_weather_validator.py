"""M5.5 manager weather containment and spacing validation."""
from __future__ import annotations

import copy

import numpy as np

from data.constants import TILE_LAND
from domain.managers.map_placement import MapPlacementManager
from domain.managers.strategic_region import StrategicRegionManager
from domain.validators.placement import validate_manager_weather_positions


def _maps_and_regions():
    province_map = np.array(
        [[1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2]],
        dtype=np.int32,
    )
    region_mgr = StrategicRegionManager()
    first = region_mgr.create_region("first")
    second = region_mgr.create_region("second")
    region_mgr.assign_province(1, first.id)
    region_mgr.assign_province(2, second.id)
    return province_map, np.full_like(province_map, TILE_LAND), region_mgr


def test_missing_manager_and_empty_weather_are_safe():
    province_map, _tile_map, region_mgr = _maps_and_regions()
    assert validate_manager_weather_positions(
        province_map, None, strategic_region_mgr=region_mgr
    ) == []
    empty = validate_manager_weather_positions(
        province_map, MapPlacementManager(), strategic_region_mgr=region_mgr
    )
    assert len(empty) == 1
    assert "no valid weather position" in empty[0].evidence


def test_multiple_valid_positions_pass_and_do_not_mutate_inputs():
    province_map, _tile_map, region_mgr = _maps_and_regions()
    manager = MapPlacementManager()
    manager.add_weather(1, 0.25, 0.25, review_status="reviewed")
    manager.add_weather(1, 1.75, 0.25, review_status="accepted")
    manager.add_weather(2, 2.25, 0.25, review_status="reviewed")
    before_map = province_map.copy()
    before_manager = copy.deepcopy(manager.to_dict())
    before_regions = copy.deepcopy(region_mgr.to_dict())

    assert validate_manager_weather_positions(
        province_map, manager, strategic_region_mgr=region_mgr
    ) == []
    assert np.array_equal(province_map, before_map)
    assert manager.to_dict() == before_manager
    assert region_mgr.to_dict() == before_regions


def test_containment_unknown_and_out_of_bounds_are_reported():
    province_map, _tile_map, region_mgr = _maps_and_regions()
    manager = MapPlacementManager()
    manager.add_weather(2, 0.5, 0.5)
    manager.add_weather(99, 1.0, 1.0)
    manager.add_weather(1, -1.0, 1.0)
    findings = validate_manager_weather_positions(
        province_map, manager, strategic_region_mgr=region_mgr, lifecycle="candidate"
    )
    assert len(findings) == 1
    assert findings[0].code == "placement.weather"
    assert findings[0].severity == "warning"
    assert "resolves to region" in findings[0].evidence
    assert "unknown strategic region" in findings[0].evidence
    assert "out of bounds" in findings[0].evidence


def test_duplicate_and_near_positions_use_minimum_spacing():
    province_map, _tile_map, region_mgr = _maps_and_regions()
    manager = MapPlacementManager()
    manager.add_weather(1, 0.5, 0.5)
    manager.add_weather(1, 0.5, 0.5)
    manager.add_weather(1, 1.25, 0.5)
    findings = validate_manager_weather_positions(
        province_map,
        manager,
        strategic_region_mgr=region_mgr,
        min_spacing=1.0,
    )
    assert len(findings) == 1
    assert "minimum spacing" in findings[0].evidence
    assert "weather#1" in findings[0].evidence
    assert "weather#2" in findings[0].evidence


def test_strict_lifecycle_promotes_weather_issue_to_blocker():
    province_map, _tile_map, region_mgr = _maps_and_regions()
    manager = MapPlacementManager()
    manager.add_weather(1, 0.5, 0.5)
    manager.add_weather(1, 0.75, 0.5)
    draft = validate_manager_weather_positions(
        province_map, manager, strategic_region_mgr=region_mgr, lifecycle="draft", min_spacing=1.0
    )
    frozen = validate_manager_weather_positions(
        province_map, manager, strategic_region_mgr=region_mgr, lifecycle="frozen", min_spacing=1.0
    )
    assert draft[0].severity == "warning"
    assert frozen[0].severity == "blocker"
    assert frozen[0].evidence == draft[0].evidence
