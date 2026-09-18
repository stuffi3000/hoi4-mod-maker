"""M5.1 placement manager snapshot and export-copy tests."""
from __future__ import annotations

import numpy as np
import pytest

from domain.managers.map_placement import MapPlacementManager
from services.export_planner import (
    _apply_province_compact_ids,
    analyze_province_compact_ids,
    plan_export,
)

pytestmark = pytest.mark.unit


def _maps_with_gaps():
    tile = np.ones((2, 6), dtype=np.uint8)
    province = np.array([[1, 1, 3, 3, 5, 5], [1, 1, 3, 3, 5, 5]], dtype=np.int32)
    terrain = np.zeros_like(province, dtype=np.uint8)
    return tile, province, terrain


def _placements():
    manager = MapPlacementManager()
    manager.set_province_slot(1, 0, 1.25, 0.5, provenance="generated")
    manager.set_province_slot(3, 1, 2.5, 0.75, provenance="authored")
    manager.set_port(5, 4.125, 1.5, sea_province=3, provenance="authored")
    return manager


def test_plan_snapshot_forks_map_placements_without_live_alias():
    tile, province, terrain = _maps_with_gaps()
    live = _placements()

    plan = plan_export(
        tile,
        province,
        terrain,
        state_mgr=None,
        map_placement_mgr=live,
        profile_name="foundation",
    )

    snapshot_manager = plan.snapshot.map_placement_mgr
    assert snapshot_manager is not live
    assert snapshot_manager.to_dict() == live.to_dict()
    snapshot_manager.set_province_slot(5, 2, 5.5, 1.5)
    assert live.get_province_slot(5, 2) is None


def test_compact_repair_remaps_snapshot_only_and_preserves_float_values():
    tile, province, terrain = _maps_with_gaps()
    live = _placements()
    plan = plan_export(
        tile,
        province,
        terrain,
        map_placement_mgr=live,
        profile_name="foundation",
    )
    actions = analyze_province_compact_ids(plan.snapshot)
    assert len(actions) == 1

    _apply_province_compact_ids(plan.snapshot, actions[0])

    copied = plan.snapshot.map_placement_mgr
    assert sorted(copied._slots) == [(1, 0), (2, 1)]
    port = copied.get_port(3)
    assert port is not None
    assert port.sea_province == 2
    assert port.x == 4.125
    assert live.get_province_slot(3, 1) is not None
    assert live.get_port(5).sea_province == 3
