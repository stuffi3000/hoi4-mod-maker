"""M5.2 Slice 1 headless placement proposal orchestration coverage."""
from __future__ import annotations

import numpy as np
import pytest

from data.constants import TILE_LAND
from data.constants import TILE_SEA
from domain.managers.map_placement import MapPlacementManager
from services.placement_proposals import PortProposalWorkflowResult
from services.placement_proposals import SlotProposalWorkflowResult
from services.placement_proposals import accept_selected_placements
from services.placement_proposals import propose_port_placements
from services.placement_proposals import propose_slot_placements

pytestmark = pytest.mark.unit


def _slot_maps():
    """Land province 1 with sea provinces 2 and 3 for slot tests."""
    province_map = np.array(
        [
            [1, 1, 1, 1, 2, 2],
            [1, 1, 1, 1, 2, 2],
            [1, 1, 1, 1, 2, 2],
            [1, 1, 1, 1, 2, 2],
            [3, 3, 3, 3, 3, 3],
            [3, 3, 3, 3, 3, 3],
        ],
        dtype=np.int32,
    )
    tile_map = np.array(
        [
            [1, 1, 1, 1, 2, 2],
            [1, 1, 1, 1, 2, 2],
            [1, 1, 1, 1, 2, 2],
            [1, 1, 1, 1, 2, 2],
            [2, 2, 2, 2, 2, 2],
            [2, 2, 2, 2, 2, 2],
        ],
        dtype=np.int32,
    )
    return province_map, tile_map


def _tiny_slot_maps():
    """Single land pixel province 5 for insufficient space tests."""
    province_map = np.array(
        [
            [5, 6, 6],
            [6, 6, 6],
            [6, 6, 6],
        ],
        dtype=np.int32,
    )
    tile_map = np.array(
        [
            [1, 2, 2],
            [2, 2, 2],
            [2, 2, 2],
        ],
        dtype=np.int32,
    )
    return province_map, tile_map


def _port_maps():
    """Coastal land province 1 adjacent to sea province 10."""
    province_map = np.array(
        [
            [1, 1, 1, 10, 10, 10],
            [1, 1, 1, 10, 10, 10],
            [1, 1, 1, 10, 10, 10],
            [1, 1, 1, 10, 10, 10],
        ],
        dtype=np.int32,
    )
    tile_map = np.array(
        [
            [1, 1, 1, 2, 2, 2],
            [1, 1, 1, 2, 2, 2],
            [1, 1, 1, 2, 2, 2],
            [1, 1, 1, 2, 2, 2],
        ],
        dtype=np.int32,
    )
    return province_map, tile_map


def _two_land_port_maps():
    """Land provinces 1 and 2 where only province 2 touches sea 10."""
    province_map = np.array(
        [
            [1, 1, 2, 2, 2, 10, 10, 10],
            [1, 1, 2, 2, 2, 10, 10, 10],
            [1, 1, 2, 2, 2, 10, 10, 10],
            [1, 1, 2, 2, 2, 10, 10, 10],
        ],
        dtype=np.int32,
    )
    tile_map = np.array(
        [
            [1, 1, 1, 1, 1, 2, 2, 2],
            [1, 1, 1, 1, 1, 2, 2, 2],
            [1, 1, 1, 1, 1, 2, 2, 2],
            [1, 1, 1, 1, 1, 2, 2, 2],
        ],
        dtype=np.int32,
    )
    return province_map, tile_map


def _slot_keys(records):
    return sorted([(int(item.province_id), int(item.slot)) for item in records])


def test_slot_workflow_generates_and_stores_generated_unreviewed():
    """Slot generation stores generated unreviewed records with diagnostics."""
    province_map, tile_map = _slot_maps()
    manager = MapPlacementManager()
    result = propose_slot_placements(
        province_map,
        tile_map,
        manager,
        province_ids=[1],
        slot_count=2,
        seed=7,
    )
    assert isinstance(result, SlotProposalWorkflowResult)
    assert len(result.proposal.slots) == 2
    assert result.diagnostics == result.proposal.diagnostics
    assert result.store_report.stored_keys == _slot_keys(result.proposal.slots)
    assert result.store_report.replaced_keys == []
    for record in result.proposal.slots:
        assert record.provenance == "generated"
        assert record.review_status == "unreviewed"
        stored = manager.get_province_slot(int(record.province_id), int(record.slot))
        assert stored is not None
        assert stored.provenance == "generated"
        assert stored.review_status == "unreviewed"
        assert float(stored.x) == float(record.x)
        assert float(stored.y) == float(record.y)


def test_slot_workflow_forwards_seed_slot_count_height_and_weights():
    """Seed slot count height and weights pass through with stable defaults."""
    province_map, tile_map = _slot_maps()
    first = MapPlacementManager()
    one = propose_slot_placements(
        province_map,
        tile_map,
        first,
        province_ids=[1],
        slot_count=1,
        seed=3,
    )
    assert len(one.proposal.slots) == 1
    second_manager = MapPlacementManager()
    three = propose_slot_placements(
        province_map,
        tile_map,
        second_manager,
        province_ids=[1],
        slot_count=3,
        seed=3,
        border_weight=0.2,
        coast_weight=0.3,
        height_weight=0.1,
        slope_weight=0.4,
        min_separation=1.0,
    )
    assert len(three.proposal.slots) == 3
    height_map = np.full(province_map.shape, 42.0, dtype=np.float64)
    height_manager = MapPlacementManager()
    heighted = propose_slot_placements(
        province_map,
        tile_map,
        height_manager,
        province_ids=[1],
        slot_count=2,
        seed=3,
        height_map=height_map,
    )
    assert len(heighted.proposal.slots) == 2
    for record in heighted.proposal.slots:
        assert float(record.height) == 42.0
        stored = height_manager.get_province_slot(
            int(record.province_id), int(record.slot)
        )
        assert float(stored.height) == 42.0


def test_slot_workflow_surfaces_explicit_diagnostics():
    """Unknown sea-only and tiny provinces surface explicit diagnostics."""
    province_map, tile_map = _slot_maps()
    manager = MapPlacementManager()
    result = propose_slot_placements(
        province_map,
        tile_map,
        manager,
        province_ids=[1, 2, 99],
        slot_count=2,
        seed=1,
    )
    codes = {(int(item.province_id), str(item.code)) for item in result.diagnostics}
    assert (2, "non_land") in codes
    assert (99, "unknown_province") in codes
    assert result.store_report.stored_keys == _slot_keys(result.proposal.slots)
    tiny_province, tiny_tile = _tiny_slot_maps()
    tiny_manager = MapPlacementManager()
    tiny = propose_slot_placements(
        tiny_province,
        tiny_tile,
        tiny_manager,
        province_ids=[5],
        slot_count=3,
        seed=1,
    )
    assert len(tiny.proposal.slots) == 1
    assert [str(item.code) for item in tiny.diagnostics] == ["insufficient_space"]
    assert tiny.store_report.stored_keys == _slot_keys(tiny.proposal.slots)


def test_port_workflow_stores_explicit_sea_mapping():
    """Port generation uses the exact sea mapping and stores unreviewed ports."""
    province_map, tile_map = _port_maps()
    manager = MapPlacementManager()
    result = propose_port_placements(
        province_map,
        tile_map,
        manager,
        {1: 10},
        seed=5,
    )
    assert isinstance(result, PortProposalWorkflowResult)
    assert len(result.proposal.ports) == 1
    assert result.diagnostics == result.proposal.diagnostics
    assert result.diagnostics == []
    port = result.proposal.ports[0]
    assert int(port.province_id) == 1
    assert int(port.sea_province) == 10
    assert port.provenance == "generated"
    assert port.review_status == "unreviewed"
    assert result.store_report.stored_ids == [1]
    stored = manager.get_port(1)
    assert stored is not None
    assert int(stored.sea_province) == 10
    assert stored.provenance == "generated"
    assert stored.review_status == "unreviewed"
    assert float(stored.x) == float(port.x)
    assert float(stored.y) == float(port.y)


def test_port_workflow_never_guesses_sea_and_surfaces_no_adjacency():
    """Unmapped or nonadjacent provinces produce diagnostics never guessed ports."""
    province_map, tile_map = _two_land_port_maps()
    manager = MapPlacementManager()
    adjacent = propose_port_placements(
        province_map,
        tile_map,
        manager,
        {2: 10},
        province_ids=[2],
        seed=2,
    )
    assert [int(item.province_id) for item in adjacent.proposal.ports] == [2]
    assert int(adjacent.proposal.ports[0].sea_province) == 10
    isolated_manager = MapPlacementManager()
    isolated = propose_port_placements(
        province_map,
        tile_map,
        isolated_manager,
        {1: 10},
        province_ids=[1],
        seed=2,
    )
    assert isolated.proposal.ports == []
    assert [(int(item.province_id), str(item.code)) for item in isolated.diagnostics] == [
        (1, "no_adjacency")
    ]
    assert isolated.store_report.stored_ids == []
    missing_manager = MapPlacementManager()
    missing = propose_port_placements(
        province_map,
        tile_map,
        missing_manager,
        {2: 10},
        province_ids=[1, 2],
        seed=2,
    )
    assert [int(item.province_id) for item in missing.proposal.ports] == [2]
    assert [(int(item.province_id), str(item.code)) for item in missing.diagnostics] == [
        (1, "missing_mapping")
    ]
    assert missing_manager.get_port(1) is None


def test_slot_replace_flag_forwards_and_protects():
    """Second slot ingestion skips then replaces only with an explicit flag."""
    province_map, tile_map = _slot_maps()
    manager = MapPlacementManager()
    first = propose_slot_placements(
        province_map,
        tile_map,
        manager,
        province_ids=[1],
        slot_count=2,
        seed=9,
    )
    assert first.store_report.stored_count == 2
    kept = propose_slot_placements(
        province_map,
        tile_map,
        manager,
        province_ids=[1],
        slot_count=2,
        seed=9,
    )
    assert kept.store_report.stored_keys == []
    assert kept.store_report.replaced_keys == []
    assert kept.store_report.skipped_count == 2
    assert {str(item.code) for item in kept.store_report.skipped} == {
        "exists_unreviewed_generated"
    }
    replaced = propose_slot_placements(
        province_map,
        tile_map,
        manager,
        province_ids=[1],
        slot_count=2,
        seed=9,
        replace_generated=True,
    )
    assert sorted(replaced.store_report.replaced_keys) == sorted(
        first.store_report.stored_keys
    )
    assert replaced.store_report.skipped == []
    accept_selected_placements(manager, slot_keys=[(1, 0)], review_status="reviewed")
    protected = propose_slot_placements(
        province_map,
        tile_map,
        manager,
        province_ids=[1],
        slot_count=2,
        seed=9,
        replace_generated=True,
    )
    assert (1, 0) not in protected.store_report.replaced_keys
    assert [
        (int(item.province_id), int(item.slot)) for item in protected.store_report.skipped
        if str(item.code) == "protected"
    ] == [(1, 0)]


def test_port_replace_flag_forwards_and_protects():
    """Second port ingestion skips then replaces only with an explicit flag."""
    province_map, tile_map = _port_maps()
    manager = MapPlacementManager()
    first = propose_port_placements(province_map, tile_map, manager, {1: 10}, seed=4)
    assert first.store_report.stored_ids == [1]
    kept = propose_port_placements(province_map, tile_map, manager, {1: 10}, seed=4)
    assert kept.store_report.stored_ids == []
    assert kept.store_report.replaced_ids == []
    assert [str(item.code) for item in kept.store_report.skipped] == [
        "exists_unreviewed_generated"
    ]
    replaced = propose_port_placements(
        province_map, tile_map, manager, {1: 10}, seed=4, replace_generated=True
    )
    assert replaced.store_report.replaced_ids == [1]
    accept_selected_placements(manager, port_ids=[1], review_status="reviewed")
    protected = propose_port_placements(
        province_map, tile_map, manager, {1: 10}, seed=4, replace_generated=True
    )
    assert protected.store_report.replaced_ids == []
    assert [str(item.code) for item in protected.store_report.skipped] == ["protected"]


def test_acceptance_accepts_only_selected_keys():
    """Acceptance touches only caller-selected slots and ports."""
    province_map, tile_map = _slot_maps()
    manager = MapPlacementManager()
    slots = propose_slot_placements(
        province_map, tile_map, manager, province_ids=[1], slot_count=2, seed=6
    )
    assert slots.store_report.stored_count == 2
    port_map, port_tile = _port_maps()
    ports = propose_port_placements(port_map, port_tile, manager, {1: 10}, seed=6)
    assert ports.store_report.stored_ids == [1]
    untouched = accept_selected_placements(manager)
    assert untouched.accepted_count == 0
    assert untouched.missing_count == 0
    assert manager.get_province_slot(1, 0).review_status == "unreviewed"
    assert manager.get_port(1).review_status == "unreviewed"
    report = accept_selected_placements(
        manager, slot_keys=[(1, 0)], port_ids=[1], review_status="reviewed"
    )
    assert report.accepted_slot_keys == [(1, 0)]
    assert report.accepted_port_ids == [1]
    assert report.missing == []
    assert manager.get_province_slot(1, 0).review_status == "reviewed"
    assert manager.get_province_slot(1, 1).review_status == "unreviewed"
    assert manager.get_port(1).review_status == "reviewed"
    second = accept_selected_placements(
        manager, slot_keys=[(1, 1)], port_ids=[7], review_status="accepted"
    )
    assert second.accepted_slot_keys == [(1, 1)]
    assert second.accepted_port_ids == []
    assert [(int(item.province_id), str(item.code)) for item in second.missing] == [
        (7, "missing")
    ]
    assert manager.get_province_slot(1, 1).review_status == "accepted"


def test_workflows_are_deterministic():
    """Identical inputs and seeds repeat identical proposals and reports."""
    province_map, tile_map = _slot_maps()
    height_map = np.full(province_map.shape, 7.0, dtype=np.float64)
    first_manager = MapPlacementManager()
    first = propose_slot_placements(
        province_map,
        tile_map,
        first_manager,
        province_ids=[1],
        slot_count=2,
        seed=11,
        height_map=height_map,
        border_weight=0.7,
        coast_weight=0.8,
        height_weight=0.3,
        slope_weight=0.9,
    )
    second_manager = MapPlacementManager()
    second = propose_slot_placements(
        province_map,
        tile_map,
        second_manager,
        province_ids=[1],
        slot_count=2,
        seed=11,
        height_map=height_map,
        border_weight=0.7,
        coast_weight=0.8,
        height_weight=0.3,
        slope_weight=0.9,
    )
    assert [item.to_dict() for item in first.proposal.slots] == [
        item.to_dict() for item in second.proposal.slots
    ]
    assert [item.to_dict() for item in [first_manager.get_province_slot(1, 0)]] == [
        item.to_dict() for item in [second_manager.get_province_slot(1, 0)]
    ]
    port_map, port_tile = _port_maps()
    port_first_manager = MapPlacementManager()
    port_first = propose_port_placements(
        port_map, port_tile, port_first_manager, {1: 10}, seed=11
    )
    port_second_manager = MapPlacementManager()
    port_second = propose_port_placements(
        port_map, port_tile, port_second_manager, {1: 10}, seed=11
    )
    assert [item.to_dict() for item in port_first.proposal.ports] == [
        item.to_dict() for item in port_second.proposal.ports
    ]
    assert port_first_manager.get_port(1).to_dict() == port_second_manager.get_port(
        1
    ).to_dict()


def test_workflows_do_not_mutate_inputs():
    """Rasters mappings and id lists keep equal copies after orchestration."""
    province_map, tile_map = _slot_maps()
    province_snapshot = province_map.copy()
    tile_snapshot = tile_map.copy()
    height_map = np.full(province_map.shape, 3.0, dtype=np.float64)
    height_snapshot = height_map.copy()
    province_ids = [1]
    province_ids_snapshot = list(province_ids)
    manager = MapPlacementManager()
    propose_slot_placements(
        province_map,
        tile_map,
        manager,
        province_ids=province_ids,
        slot_count=2,
        seed=8,
        height_map=height_map,
    )
    assert np.array_equal(province_map, province_snapshot)
    assert np.array_equal(tile_map, tile_snapshot)
    assert np.array_equal(height_map, height_snapshot)
    assert province_ids == province_ids_snapshot
    port_map, port_tile = _port_maps()
    port_province_snapshot = port_map.copy()
    port_tile_snapshot = port_tile.copy()
    sea_mapping = {1: 10}
    sea_snapshot = dict(sea_mapping)
    port_ids = [1]
    port_ids_snapshot = list(port_ids)
    port_manager = MapPlacementManager()
    propose_port_placements(
        port_map,
        port_tile,
        port_manager,
        sea_mapping,
        province_ids=port_ids,
        seed=8,
    )
    assert np.array_equal(port_map, port_province_snapshot)
    assert np.array_equal(port_tile, port_tile_snapshot)
    assert sea_mapping == sea_snapshot
    assert port_ids == port_ids_snapshot
    assert TILE_LAND == 1
    assert TILE_SEA == 2


def test_port_workflow_rejects_missing_and_invalid_mappings():
    """Explicit sea mapping is required and invalid values become diagnostics."""
    province_map, tile_map = _port_maps()
    manager = MapPlacementManager()
    with pytest.raises(TypeError):
        propose_port_placements(province_map, tile_map, manager, None)
    with pytest.raises(ValueError):
        propose_port_placements(province_map, tile_map, manager, [(1, 10)])
    invalid_manager = MapPlacementManager()
    invalid = propose_port_placements(
        province_map, tile_map, invalid_manager, {1: 0}, seed=1
    )
    assert invalid.proposal.ports == []
    assert [(int(item.province_id), str(item.code)) for item in invalid.diagnostics] == [
        (1, "invalid_mapping")
    ]
    assert invalid.store_report.stored_ids == []
    assert invalid_manager.get_port(1) is None
    unknown_manager = MapPlacementManager()
    unknown = propose_port_placements(
        province_map, tile_map, unknown_manager, {1: 999}, seed=1
    )
    assert unknown.proposal.ports == []
    assert [(int(item.province_id), str(item.code)) for item in unknown.diagnostics] == [
        (1, "unknown_sea")
    ]
