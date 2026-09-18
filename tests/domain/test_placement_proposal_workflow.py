"""M5.2 proposal-to-manager workflow tests (no game install)."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from domain.generators.placement import (
    PlacementProposalResult,
    PortProposalResult,
    accept_stored_placements,
    generate_placement_proposals,
    generate_port_proposals,
    store_placement_proposals,
    store_port_proposals,
)
from domain.managers.map_placement import MapPlacementManager

pytestmark = pytest.mark.unit


def _slot_map():
    province = np.zeros((9, 11), dtype=np.int32)
    province[1:8, 1:10] = 1
    province[2:6, 6:10] = 2
    tile = np.full(province.shape, TILE_SEA, dtype=np.uint8)
    tile[province == 1] = TILE_LAND
    tile[province == 2] = TILE_LAND
    return province, tile


def _coastal_map():
    province = np.array(
        [[1, 1, 1, 2], [1, 1, 1, 2], [1, 1, 1, 2]], dtype=np.int32
    )
    tile = np.full(province.shape, TILE_LAND, dtype=np.uint8)
    tile[province == 2] = TILE_SEA
    return province, tile


def _slot_snapshot(result):
    return [
        (
            record.province_id, record.slot, record.x, record.y,
            record.rotation, record.height, record.meaning,
            record.provenance, record.review_status,
        )
        for record in result.slots
    ]


def _port_snapshot(result):
    return [
        (
            record.province_id, record.x, record.y, record.rotation,
            record.height, record.sea_province, record.provenance,
            record.review_status,
        )
        for record in result.ports
    ]


def test_slot_ingestion_stays_generated_unreviewed():
    province, tile = _slot_map()
    result = generate_placement_proposals(
        province, tile, province_ids=[1], slot_count=3, seed=7,
    )
    before = _slot_snapshot(result)
    manager = MapPlacementManager()
    report = store_placement_proposals(manager, result)
    assert report.stored_keys == [(1, 0), (1, 1), (1, 2)]
    assert report.replaced_keys == []
    assert report.skipped == []
    assert report.stored_count == 3
    for record in result.slots:
        stored = manager.get_province_slot(record.province_id, record.slot)
        assert stored is not None
        assert stored is not record
        assert stored.provenance == "generated"
        assert stored.review_status == "unreviewed"
        assert stored.x == record.x
        assert stored.y == record.y
        assert stored.rotation == record.rotation
        assert stored.height == record.height
        assert stored.meaning == record.meaning
        assert all(
            isinstance(value, float)
            for value in (stored.x, stored.y, stored.rotation, stored.height)
        )
    assert _slot_snapshot(result) == before


def test_port_ingestion_preserves_floats_and_sea():
    province, tile = _coastal_map()
    height = np.full(province.shape, 12.0, dtype=np.float64)
    height[1, 1] = 77.5
    result = generate_port_proposals(
        province, tile, {1: 2}, height_map=height, province_ids=[1], seed=5,
    )
    assert len(result.ports) == 1
    before = _port_snapshot(result)
    manager = MapPlacementManager()
    report = store_port_proposals(manager, result)
    assert report.stored_ids == [1]
    assert report.replaced_ids == []
    assert report.skipped == []
    proposal = result.ports[0]
    stored = manager.get_port(1)
    assert stored is not None
    assert stored is not proposal
    assert stored.provenance == "generated"
    assert stored.review_status == "unreviewed"
    assert stored.x == proposal.x
    assert stored.y == proposal.y
    assert stored.rotation == proposal.rotation
    assert stored.height == proposal.height
    assert stored.sea_province == 2
    assert stored.sea_province == proposal.sea_province
    assert all(
        isinstance(value, float)
        for value in (stored.x, stored.y, stored.rotation, stored.height)
    )
    assert _port_snapshot(result) == before


def test_ingestion_never_marks_anything_reviewed():
    province, tile = _slot_map()
    slots = generate_placement_proposals(
        province, tile, province_ids=[1], slot_count=2, seed=3,
    )
    coast_province, coast_tile = _coastal_map()
    ports = generate_port_proposals(
        coast_province, coast_tile, {1: 2}, province_ids=[1],
    )
    manager = MapPlacementManager()
    store_placement_proposals(manager, slots)
    store_port_proposals(manager, ports)
    assert [r.review_status for r in manager.list_province_slots()] == [
        "unreviewed", "unreviewed",
    ]
    assert [p.review_status for p in manager.list_ports()] == ["unreviewed"]
    assert all(r.provenance == "generated" for r in manager.list_province_slots())
    assert all(p.provenance == "generated" for p in manager.list_ports())


def test_authored_and_reviewed_conflicts_are_kept_by_default():
    province, tile = _slot_map()
    result = generate_placement_proposals(
        province, tile, province_ids=[1], slot_count=3, seed=7,
    )
    manager = MapPlacementManager()
    manager.set_province_slot(1, 0, 0.5, 0.5, provenance="authored")
    manager.set_province_slot(
        1, 1, 0.5, 1.5, provenance="generated", review_status="unreviewed",
    )
    manager.mark_slot_reviewed(1, 1, "reviewed")
    report = store_placement_proposals(manager, result)
    assert report.stored_keys == [(1, 2)]
    assert report.replaced_keys == []
    assert [(d.province_id, d.slot, d.code) for d in report.skipped] == [
        (1, 0, "protected"),
        (1, 1, "protected"),
    ]
    assert manager.get_province_slot(1, 0).x == 0.5
    assert manager.get_province_slot(1, 0).provenance == "authored"
    assert manager.get_province_slot(1, 1).review_status == "reviewed"
    assert manager.get_province_slot(1, 2).provenance == "generated"
    assert manager.get_province_slot(1, 2).review_status == "unreviewed"


def test_port_authored_conflict_is_kept_by_default():
    coast_province, coast_tile = _coastal_map()
    result = generate_port_proposals(
        coast_province, coast_tile, {1: 2}, province_ids=[1],
    )
    manager = MapPlacementManager()
    manager.set_port(1, 0.5, 0.5, sea_province=2, provenance="authored")
    report = store_port_proposals(manager, result)
    assert report.stored_ids == []
    assert report.replaced_ids == []
    assert [(d.province_id, d.code) for d in report.skipped] == [
        (1, "protected"),
    ]
    assert manager.get_port(1).x == 0.5
    assert manager.get_port(1).provenance == "authored"


def test_explicit_replacement_only_replaces_unreviewed_generated():
    province, tile = _slot_map()
    first = generate_placement_proposals(
        province, tile, province_ids=[1], slot_count=3, seed=7,
    )
    from domain.managers.map_placement import ProvincePositionSlot
    second = PlacementProposalResult(
        slots=[
            ProvincePositionSlot(
                province_id=record.province_id,
                slot=record.slot,
                x=float(record.x) + 100.0,
                y=float(record.y),
                rotation=float(record.rotation),
                height=float(record.height),
                meaning=record.meaning,
                provenance="generated",
                review_status="unreviewed",
            )
            for record in first.slots
        ],
        diagnostics=[],
    )
    manager = MapPlacementManager()
    store_placement_proposals(manager, first)
    manager.mark_slot_reviewed(1, 1, "reviewed")
    manager.set_province_slot(1, 2, 0.5, 0.5, provenance="authored")
    kept_reviewed = copy.deepcopy(manager.get_province_slot(1, 1).__dict__)
    kept_authored = copy.deepcopy(manager.get_province_slot(1, 2).__dict__)
    default_report = store_placement_proposals(manager, second)
    assert default_report.stored_keys == []
    assert default_report.replaced_keys == []
    assert [(d.slot, d.code) for d in default_report.skipped] == [
        (0, "exists_unreviewed_generated"),
        (1, "protected"),
        (2, "protected"),
    ]
    replaced_report = store_placement_proposals(
        manager, second, replace_generated=True,
    )
    assert replaced_report.stored_keys == []
    assert replaced_report.replaced_keys == [(1, 0)]
    assert [(d.slot, d.code) for d in replaced_report.skipped] == [
        (1, "protected"),
        (2, "protected"),
    ]
    wanted = {(r.slot): (r.x, r.y) for r in second.slots}
    assert (manager.get_province_slot(1, 0).x, manager.get_province_slot(1, 0).y) == wanted[0]
    assert manager.get_province_slot(1, 0).provenance == "generated"
    assert manager.get_province_slot(1, 0).review_status == "unreviewed"
    assert manager.get_province_slot(1, 1).__dict__ == kept_reviewed
    assert manager.get_province_slot(1, 2).__dict__ == kept_authored


def test_port_replacement_only_replaces_unreviewed_generated():
    coast_province, coast_tile = _coastal_map()
    result = generate_port_proposals(
        coast_province, coast_tile, {1: 2}, province_ids=[1], seed=5,
    )
    manager = MapPlacementManager()
    store_port_proposals(manager, result)
    manager.mark_port_reviewed(1, "reviewed")
    reviewed_x = manager.get_port(1).x
    repeat = store_port_proposals(manager, result, replace_generated=True)
    assert repeat.replaced_ids == []
    assert [d.code for d in repeat.skipped] == ["protected"]
    assert manager.get_port(1).x == reviewed_x
    assert manager.get_port(1).review_status == "reviewed"
    fresh = MapPlacementManager()
    store_port_proposals(fresh, result)
    changed = PortProposalResult(
        ports=[
            type(result.ports[0])(
                province_id=1, x=0.5, y=0.5, rotation=0.0, height=1.0,
                sea_province=2, provenance="generated",
                review_status="unreviewed",
            )
        ],
        diagnostics=[],
    )
    replaced = store_port_proposals(fresh, changed, replace_generated=True)
    assert replaced.replaced_ids == [1]
    assert fresh.get_port(1).x == 0.5
    assert fresh.get_port(1).height == 1.0
    assert fresh.get_port(1).provenance == "generated"
    assert fresh.get_port(1).review_status == "unreviewed"


def test_explicit_acceptance_changes_only_selected_records():
    province, tile = _slot_map()
    slots = generate_placement_proposals(
        province, tile, province_ids=[1], slot_count=3, seed=7,
    )
    coast_province, coast_tile = _coastal_map()
    ports = generate_port_proposals(
        coast_province, coast_tile, {1: 2}, province_ids=[1],
    )
    manager = MapPlacementManager()
    store_placement_proposals(manager, slots)
    store_port_proposals(manager, ports)
    report = accept_stored_placements(
        manager, slot_keys=[(1, 2), (1, 0)], port_ids=[],
        review_status="reviewed",
    )
    assert report.accepted_slot_keys == [(1, 0), (1, 2)]
    assert report.accepted_port_ids == []
    assert report.missing == []
    assert manager.get_province_slot(1, 0).review_status == "reviewed"
    assert manager.get_province_slot(1, 2).review_status == "reviewed"
    assert manager.get_province_slot(1, 1).review_status == "unreviewed"
    assert manager.get_port(1).review_status == "unreviewed"
    assert manager.get_province_slot(1, 0).provenance == "generated"
    port_report = accept_stored_placements(
        manager, port_ids=[1], review_status="accepted",
    )
    assert port_report.accepted_port_ids == [1]
    assert manager.get_port(1).review_status == "accepted"
    assert manager.get_province_slot(1, 1).review_status == "unreviewed"


def test_acceptance_reports_missing_and_rejects_bad_status():
    manager = MapPlacementManager()
    manager.set_province_slot(1, 0, 0.5, 0.5, provenance="generated")
    report = accept_stored_placements(
        manager, slot_keys=[(1, 0), (1, 5), (9, 0)], port_ids=[7],
    )
    assert report.accepted_slot_keys == [(1, 0)]
    assert report.accepted_port_ids == []
    assert [(d.kind, d.province_id, d.slot, d.code) for d in report.missing] == [
        ("port", 7, None, "missing"),
        ("slot", 1, 5, "missing"),
        ("slot", 9, 0, "missing"),
    ]
    assert manager.get_province_slot(1, 0).review_status == "reviewed"
    with pytest.raises(ValueError):
        accept_stored_placements(manager, slot_keys=[(1, 0)], review_status="unreviewed")
    with pytest.raises(ValueError):
        accept_stored_placements(manager, port_ids=[1], review_status="final")
    assert manager.get_province_slot(1, 0).review_status == "reviewed"


def test_reports_are_deterministically_ordered():
    province, tile = _slot_map()
    forward = generate_placement_proposals(
        province, tile, province_ids=[1, 2], slot_count=2, seed=11,
    )
    backward = generate_placement_proposals(
        province, tile, province_ids=[2, 1], slot_count=2, seed=11,
    )
    assert forward == backward
    first_manager = MapPlacementManager()
    second_manager = MapPlacementManager()
    first_report = store_placement_proposals(first_manager, forward)
    second_report = store_placement_proposals(second_manager, backward)
    assert first_report == second_report
    assert first_report.stored_keys == sorted(first_report.stored_keys)
    repeat_report = store_placement_proposals(first_manager, forward)
    assert repeat_report.stored_keys == []
    assert [d.code for d in repeat_report.skipped] == [
        "exists_unreviewed_generated"
    ] * 4
    keys = [(d.province_id, d.slot) for d in repeat_report.skipped]
    assert keys == sorted(keys)
    coast_province, coast_tile = _coastal_map()
    ports = generate_port_proposals(
        coast_province, coast_tile, {1: 2}, province_ids=[1],
    )
    port_manager = MapPlacementManager()
    first_port = store_port_proposals(port_manager, ports)
    second_port = store_port_proposals(port_manager, ports)
    assert first_port.stored_ids == [1]
    assert second_port.stored_ids == []
    assert [d.code for d in second_port.skipped] == [
        "exists_unreviewed_generated"
    ]


def test_exact_floats_and_no_aliasing_or_mutation():
    province, tile = _slot_map()
    height = np.zeros(province.shape, dtype=np.float64)
    height[:] = 3.25
    height[4, 3] = 9.75
    result = generate_placement_proposals(
        province, tile, height, province_ids=[1], slot_count=2, seed=7,
    )
    before = _slot_snapshot(result)
    manager = MapPlacementManager()
    store_placement_proposals(manager, result)
    for record in result.slots:
        stored = manager.get_province_slot(record.province_id, record.slot)
        col = int(stored.x - 0.5)
        row = int(stored.y - 0.5)
        assert stored.x == float(col) + 0.5
        assert stored.y == float(row) + 0.5
        assert stored.height == float(height[row, col])
    stored = manager.get_province_slot(1, 0)
    stored.x = 12345.0
    assert result.slots[0].x != 12345.0
    assert _slot_snapshot(result) == before
    coast_province, coast_tile = _coastal_map()
    ports = generate_port_proposals(
        coast_province, coast_tile, {1: 2}, province_ids=[1],
    )
    port_before = _port_snapshot(ports)
    port_manager = MapPlacementManager()
    store_port_proposals(port_manager, ports)
    port_manager.get_port(1).sea_province = 99
    assert ports.ports[0].sea_province == 2
    assert _port_snapshot(ports) == port_before


def test_inputs_are_validated_defensively():
    province, tile = _slot_map()
    slots = generate_placement_proposals(
        province, tile, province_ids=[1], slot_count=1, seed=1,
    )
    coast_province, coast_tile = _coastal_map()
    ports = generate_port_proposals(
        coast_province, coast_tile, {1: 2}, province_ids=[1],
    )
    manager = MapPlacementManager()
    with pytest.raises(TypeError):
        store_placement_proposals(None, slots)
    with pytest.raises(TypeError):
        store_placement_proposals(object(), slots)
    with pytest.raises(TypeError):
        store_placement_proposals(manager, ports)
    with pytest.raises(TypeError):
        store_port_proposals(manager, slots)
    with pytest.raises(ValueError):
        store_placement_proposals(manager, slots, replace_generated=1)
    with pytest.raises(ValueError):
        store_port_proposals(manager, ports, replace_generated="yes")
    with pytest.raises(TypeError):
        accept_stored_placements(manager, slot_keys=[(1, "zero")])
    with pytest.raises(ValueError):
        accept_stored_placements(manager, slot_keys=[(1, 6)])
    with pytest.raises(ValueError):
        accept_stored_placements(manager, port_ids=[0])
    assert isinstance(slots, PlacementProposalResult)
    assert isinstance(ports, PortProposalResult)


def test_ingestion_rejects_pre_reviewed_proposals_before_mutating_manager():
    province, tile = _slot_map()
    slots = generate_placement_proposals(
        province, tile, province_ids=[1], slot_count=1, seed=1,
    )
    slots.slots[0].review_status = "reviewed"
    manager = MapPlacementManager()
    with pytest.raises(ValueError, match="generated and unreviewed"):
        store_placement_proposals(manager, slots)
    assert manager.count() == 0

    coast_province, coast_tile = _coastal_map()
    ports = generate_port_proposals(
        coast_province, coast_tile, {1: 2}, province_ids=[1],
    )
    ports.ports[0].provenance = "authored"
    with pytest.raises(ValueError, match="generated and unreviewed"):
        store_port_proposals(manager, ports)
    assert manager.count() == 0
