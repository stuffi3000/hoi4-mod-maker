"""PlacementController unit tests (M5.2 integration slice)."""

from __future__ import annotations

import numpy as np
import pytest

from commands.history import CommandHistory
from controllers.placement import PlacementController
from data.constants import TILE_LAND, TILE_SEA
from model.events import EventBus
from model.project import Project

__all__ = ["placement_setup"]


def _install_maps(project, province_map, tile_map, height_value=40):
    """Install small synthetic rasters without touching global map size."""
    project.map_data.province_map = np.array(province_map, dtype=np.int32)
    project.map_data.tile_map = np.array(tile_map, dtype=np.uint8)
    project.map_data.height_map = np.full(
        project.map_data.province_map.shape, height_value, dtype=np.uint8
    )


def _make_slot_maps():
    """Return an 8x8 single-land-province map pair for slot proposals."""
    province_map = np.ones((8, 8), dtype=np.int32)
    tile_map = np.full((8, 8), TILE_LAND, dtype=np.uint8)
    return province_map, tile_map


def _make_port_maps():
    """Return a 6x6 coastal map where land province 1 borders sea province 2."""
    province_map = np.ones((6, 6), dtype=np.int32)
    province_map[:, 3:] = 2
    tile_map = np.full((6, 6), TILE_LAND, dtype=np.uint8)
    tile_map[:, 3:] = TILE_SEA
    return province_map, tile_map


@pytest.fixture
def placement_setup():
    """Create Project, CommandHistory, and PlacementController."""
    bus = EventBus()
    project = Project(event_bus=bus)
    history = CommandHistory(event_bus=bus)
    controller = PlacementController(project, history)
    return controller, project, history


def _placement_events(bus):
    """Collect placement_changed events in order."""
    seen = []
    bus.subscribe("placement_changed", lambda event: seen.append(event))
    return seen


def test_propose_slots_delegates_and_stays_unreviewed(placement_setup):
    """Slot proposals are stored generated/unreviewed with dirty and event."""
    controller, project, history = placement_setup
    province_map, tile_map = _make_slot_maps()
    _install_maps(project, province_map, tile_map)
    events = _placement_events(project.event_bus)

    assert not project.is_dirty
    result = controller.propose_slots(slot_count=3, seed=1)

    assert result.store_report.stored_keys == [(1, 0), (1, 1), (1, 2)]
    records = project.map_placement_mgr.list_province_slots()
    assert len(records) == 3
    for record in records:
        assert record.provenance == "generated"
        assert record.review_status == "unreviewed"
    assert project.is_dirty
    assert [event.data.get("action") for event in events] == ["proposed_slots"]
    assert history.can_undo


def test_propose_ports_forwards_explicit_mapping(placement_setup):
    """Port proposals use exactly the caller supplied sea mapping."""
    controller, project, history = placement_setup
    province_map, tile_map = _make_port_maps()
    _install_maps(project, province_map, tile_map)
    events = _placement_events(project.event_bus)

    result = controller.propose_ports({1: 2}, seed=1)

    assert result.store_report.stored_ids == [1]
    record = project.map_placement_mgr.get_port(1)
    assert record is not None
    assert record.sea_province == 2
    assert record.provenance == "generated"
    assert record.review_status == "unreviewed"
    assert project.is_dirty
    assert [event.data.get("action") for event in events] == ["proposed_ports"]
    assert history.can_undo


def test_propose_ports_requires_explicit_mapping(placement_setup):
    """A missing or non-mapping sea argument is rejected without changes."""
    controller, project, history = placement_setup
    province_map, tile_map = _make_port_maps()
    _install_maps(project, province_map, tile_map)
    events = _placement_events(project.event_bus)

    with pytest.raises(TypeError):
        controller.propose_ports(None)
    with pytest.raises(ValueError):
        controller.propose_ports([(1, 2)])

    assert project.map_placement_mgr.list_ports() == []
    assert not project.is_dirty
    assert events == []
    assert not history.can_undo


def test_propose_ports_never_guesses_sea(placement_setup):
    """An unknown mapped sea yields a diagnostic and no stored record."""
    controller, project, history = placement_setup
    province_map, tile_map = _make_port_maps()
    _install_maps(project, province_map, tile_map)
    events = _placement_events(project.event_bus)

    result = controller.propose_ports({1: 999}, seed=1)

    assert result.store_report.stored_ids == []
    assert len(result.proposal.diagnostics) == 1
    assert project.map_placement_mgr.list_ports() == []
    assert not project.is_dirty
    assert events == []
    assert not history.can_undo


def test_repeat_propose_without_replace_is_noop(placement_setup):
    """A second identical proposal stores nothing and emits no event."""
    controller, project, history = placement_setup
    province_map, tile_map = _make_slot_maps()
    _install_maps(project, province_map, tile_map)
    controller.propose_slots(slot_count=2, seed=1)
    undo_depth = len(history._undo_stack)
    events = _placement_events(project.event_bus)

    result = controller.propose_slots(slot_count=2, seed=1)

    assert result.store_report.stored_keys == []
    assert result.store_report.replaced_keys == []
    assert len(result.store_report.skipped) == 2
    assert len(history._undo_stack) == undo_depth
    assert events == []
    assert len(project.map_placement_mgr.list_province_slots()) == 2


def test_generated_records_unreviewed_until_selected_acceptance(placement_setup):
    """Only explicitly selected keys advance past unreviewed."""
    controller, project, _ = placement_setup
    province_map, tile_map = _make_slot_maps()
    _install_maps(project, province_map, tile_map)
    controller.propose_slots(slot_count=2, seed=1)
    province_map, tile_map = _make_port_maps()
    _install_maps(project, province_map, tile_map)
    controller.propose_ports({1: 2}, seed=1)

    assert all(
        record.review_status == "unreviewed"
        for record in project.map_placement_mgr.list_province_slots()
    )
    assert all(
        record.review_status == "unreviewed"
        for record in project.map_placement_mgr.list_ports()
    )

    report = controller.accept_selected(slot_keys=[(1, 0)], review_status="reviewed")

    assert report.accepted_slot_keys == [(1, 0)]
    assert report.accepted_port_ids == []
    assert project.map_placement_mgr.get_province_slot(1, 0).review_status == "reviewed"
    assert project.map_placement_mgr.get_province_slot(1, 1).review_status == "unreviewed"
    assert project.map_placement_mgr.get_port(1).review_status == "unreviewed"

    report = controller.accept_selected(port_ids=[1], review_status="accepted")

    assert report.accepted_port_ids == [1]
    assert project.map_placement_mgr.get_port(1).review_status == "accepted"
    assert project.map_placement_mgr.get_province_slot(1, 1).review_status == "unreviewed"


def test_accept_selected_noop_records_nothing(placement_setup):
    """Empty or missing-only acceptance changes nothing observable."""
    controller, project, history = placement_setup
    province_map, tile_map = _make_slot_maps()
    _install_maps(project, province_map, tile_map)
    events = _placement_events(project.event_bus)

    empty_report = controller.accept_selected()

    assert empty_report.accepted_count == 0
    assert empty_report.missing_count == 0
    assert not project.is_dirty
    assert events == []
    assert not history.can_undo

    missing_report = controller.accept_selected(
        slot_keys=[(99, 0)], port_ids=[99], review_status="reviewed"
    )

    assert missing_report.accepted_count == 0
    assert missing_report.missing_count == 2
    assert not project.is_dirty
    assert events == []
    assert not history.can_undo


def test_accept_selected_marks_dirty_and_emits_event(placement_setup):
    """Selected acceptance marks dirty and emits a stable event."""
    controller, project, history = placement_setup
    province_map, tile_map = _make_slot_maps()
    _install_maps(project, province_map, tile_map)
    controller.propose_slots(slot_count=2, seed=1)
    events = _placement_events(project.event_bus)
    undo_depth = len(history._undo_stack)

    report = controller.accept_selected(slot_keys=[(1, 1)], review_status="reviewed")

    assert report.accepted_slot_keys == [(1, 1)]
    assert project.is_dirty
    assert [event.data.get("action") for event in events] == ["accepted"]
    assert len(history._undo_stack) == undo_depth + 1


def test_history_undo_redo_restores_slot_state(placement_setup):
    """Undo and redo restore the slot manager snapshot."""
    controller, project, history = placement_setup
    province_map, tile_map = _make_slot_maps()
    _install_maps(project, province_map, tile_map)
    controller.propose_slots(slot_count=2, seed=1)
    assert len(project.map_placement_mgr.list_province_slots()) == 2

    assert history.undo()
    assert project.map_placement_mgr.list_province_slots() == []

    assert history.redo()
    keys = [
        record.key() for record in project.map_placement_mgr.list_province_slots()
    ]
    assert keys == [(1, 0), (1, 1)]

    controller.accept_selected(slot_keys=[(1, 0)], review_status="reviewed")
    assert project.map_placement_mgr.get_province_slot(1, 0).review_status == "reviewed"

    assert history.undo()
    assert project.map_placement_mgr.get_province_slot(1, 0).review_status == "unreviewed"

    assert history.redo()
    assert project.map_placement_mgr.get_province_slot(1, 0).review_status == "reviewed"


def test_history_undo_redo_restores_port_state(placement_setup):
    """Undo and redo restore the port manager snapshot."""
    controller, project, history = placement_setup
    province_map, tile_map = _make_port_maps()
    _install_maps(project, province_map, tile_map)
    controller.propose_ports({1: 2}, seed=1)
    assert project.map_placement_mgr.get_port(1) is not None

    assert history.undo()
    assert project.map_placement_mgr.get_port(1) is None

    assert history.redo()
    record = project.map_placement_mgr.get_port(1)
    assert record is not None
    assert record.sea_province == 2
    assert record.review_status == "unreviewed"

    controller.accept_selected(port_ids=[1], review_status="accepted")
    assert project.map_placement_mgr.get_port(1).review_status == "accepted"

    assert history.undo()
    assert project.map_placement_mgr.get_port(1).review_status == "unreviewed"

    assert history.redo()
    assert project.map_placement_mgr.get_port(1).review_status == "accepted"

