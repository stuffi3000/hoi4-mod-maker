"""M5 foundation placement completeness/review gate tests."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from domain.managers.map_placement import MapPlacementManager
from domain.validators.placement import (
    validate_manager_placement_completeness,
)

pytestmark = pytest.mark.unit


def _maps():
    province = np.array(
        [
            [1, 1, 2, 2, 3],
            [1, 1, 2, 2, 3],
            [1, 1, 2, 2, 3],
        ],
        dtype=np.int32,
    )
    tile = np.full(province.shape, TILE_LAND, dtype=np.uint8)
    tile[:, 4] = TILE_SEA
    return province, tile


def _complete(manager, province_id, status="reviewed"):
    for slot in range(6):
        manager.set_province_slot(
            province_id,
            slot,
            float(slot) + 0.5,
            1.5,
            provenance="authored",
            review_status=status,
        )


def _by_code(findings):
    return {finding.code: finding for finding in findings}


def test_complete_reviewed_and_accepted_land_slots_pass_and_sea_is_optional():
    province, tile = _maps()
    manager = MapPlacementManager()
    _complete(manager, 1, "reviewed")
    _complete(manager, 2, "accepted")

    assert validate_manager_placement_completeness(
        province, tile, manager, lifecycle="frozen"
    ) == []


def test_missing_incomplete_and_unreviewed_slots_change_severity_by_lifecycle():
    province, tile = _maps()
    manager = MapPlacementManager()
    _complete(manager, 1, "reviewed")
    for slot in range(5):
        manager.set_province_slot(
            2,
            slot,
            0.5 + slot,
            0.5,
            provenance="generated",
            review_status="unreviewed" if slot == 0 else "reviewed",
        )

    draft = _by_code(
        validate_manager_placement_completeness(
            province, tile, manager, lifecycle="candidate"
        )
    )
    frozen = _by_code(
        validate_manager_placement_completeness(
            province, tile, manager, lifecycle="frozen"
        )
    )
    assert draft["placement.completeness"].severity == "warning"
    assert draft["placement.review"].severity == "warning"
    assert frozen["placement.completeness"].severity == "blocker"
    assert frozen["placement.review"].severity == "blocker"
    assert 2 in frozen["placement.completeness"].affected_ids


def test_existing_unreviewed_objects_are_reported_but_reviewed_objects_pass():
    province, tile = _maps()
    manager = MapPlacementManager()
    _complete(manager, 1)
    _complete(manager, 2)
    building_id = manager.add_building(
        1,
        "bunker",
        0.5,
        0.5,
        provenance="generated",
        review_status="unreviewed",
    )
    manager.set_port(
        1,
        1.5,
        1.5,
        sea_province=3,
        provenance="generated",
        review_status="unreviewed",
    )
    manager.add_weather(
        7,
        1.5,
        1.5,
        provenance="generated",
        review_status="unreviewed",
    )
    findings = _by_code(
        validate_manager_placement_completeness(
            province, tile, manager, lifecycle="frozen"
        )
    )
    assert findings["placement.review"].severity == "blocker"
    assert "building" in findings["placement.review"].evidence
    assert "port" in findings["placement.review"].evidence
    assert "weather" in findings["placement.review"].evidence

    manager.mark_building_reviewed(building_id, "reviewed")
    manager.mark_port_reviewed(1, "reviewed")
    weather_id = manager.list_weather()[0].id
    manager.mark_weather_reviewed(weather_id, "reviewed")
    assert validate_manager_placement_completeness(
        province, tile, manager, lifecycle="frozen"
    ) == []


def test_malformed_duck_typed_records_are_reported_without_mutation():
    province, tile = _maps()

    class DuckManager:
        def list_province_slots(self):
            return [
                {"province_id": 1, "slot": "bad", "review_status": "unreviewed"},
                object(),
            ]

        def list_buildings(self):
            return [{"province_id": 1, "review_status": "unreviewed"}]

        def list_ports(self):
            return None

        def list_weather(self):
            return [{"region_id": 7, "review_status": "unreviewed"}]

    manager = DuckManager()
    before = copy.deepcopy(manager.__dict__)
    first = validate_manager_placement_completeness(
        province, tile, manager, lifecycle="frozen"
    )
    second = validate_manager_placement_completeness(
        province, tile, manager, lifecycle="frozen"
    )
    assert first == second
    assert [finding.code for finding in first] == [
        "placement.completeness",
        "placement.review",
    ]
    assert manager.__dict__ == before


def test_planner_uses_the_gate_only_when_a_manager_is_supplied():
    from services.export_planner import plan_export

    province, tile = _maps()
    empty = MapPlacementManager()
    blocked = plan_export(
        tile,
        province,
        state_mgr=None,
        country_mgr=None,
        profile_name="foundation",
        lifecycle="frozen",
        map_placement_mgr=empty,
    )
    assert any(
        finding.code == "placement.completeness"
        and finding.severity == "blocker"
        for finding in blocked.findings
    )
    assert any("land province placement groups" in blocker for blocker in blocked.blockers)

    legacy = plan_export(
        tile,
        province,
        state_mgr=None,
        country_mgr=None,
        profile_name="foundation",
        lifecycle="frozen",
    )
    assert not any(
        finding.code == "placement.completeness" for finding in legacy.findings
    )
