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

def _seed_transform_records(project):
    """Seed one record per transform kind with fractional values."""
    mgr = project.map_placement_mgr
    mgr.set_province_slot(
        1, 0, x=10.5, y=20.25, rotation=30.5, height=2.75,
        meaning="capital", provenance="authored", review_status="reviewed",
    )
    mgr.set_port(
        2, x=-4.5, y=8.25, rotation=15.5, height=3.5,
        sea_province=9, provenance="imported", review_status="accepted",
    )
    building_id = mgr.add_building(
        province_id=3, building_type="arms_factory",
        x=1.25, y=2.5, rotation=90.5, height=0.5,
        state_id=5, provenance="generated", review_status="unreviewed",
    )
    weather_id = mgr.add_weather(
        region_id=7, x=100.125, y=-50.75, rotation=180.25, height=4.125,
        size="large", kind="storm",
        provenance="fallback", review_status="unreviewed",
    )
    return building_id, weather_id


def test_update_transform_slot_fractional_preserves_fields(placement_setup):
    """Slot update applies fractional values and preserves metadata."""
    controller, project, history = placement_setup
    building_id, weather_id = _seed_transform_records(project)
    events = _placement_events(project.event_bus)
    assert not project.is_dirty
    undo_depth = len(history._undo_stack)

    changed = controller.update_transform(
        "slot", (1, 0), x=12.5, y=-3.75, rotation=45.25, height=1.5
    )

    assert changed is True
    record = project.map_placement_mgr.get_province_slot(1, 0)
    assert (record.x, record.y, record.rotation, record.height) == (12.5, -3.75, 45.25, 1.5)
    assert isinstance(record.x, float)
    assert isinstance(record.rotation, float)
    assert record.meaning == "capital"
    assert record.provenance == "authored"
    assert record.review_status == "reviewed"
    assert project.is_dirty
    assert [event.data.get("action") for event in events] == ["updated_transform"]
    assert events[0].data.get("kind") == "slot"
    assert events[0].data.get("key") == (1, 0)
    assert len(history._undo_stack) == undo_depth + 1
    assert history._undo_stack[-1]._fields == ["_slots"]
    assert project.map_placement_mgr.get_port(2).x == -4.5
    assert project.map_placement_mgr.get_building(building_id).x == 1.25
    assert project.map_placement_mgr.get_weather(weather_id).x == 100.125


def test_update_transform_port_fractional_preserves_fields(placement_setup):
    """Port update applies fractional values and preserves sea link."""
    controller, project, history = placement_setup
    _seed_transform_records(project)
    events = _placement_events(project.event_bus)

    changed = controller.update_transform(
        "port", 2, x=0.5, y=-7.75, rotation=180.5, height=0.25
    )

    assert changed is True
    record = project.map_placement_mgr.get_port(2)
    assert (record.x, record.y, record.rotation, record.height) == (0.5, -7.75, 180.5, 0.25)
    assert isinstance(record.y, float)
    assert record.sea_province == 9
    assert record.provenance == "imported"
    assert record.review_status == "accepted"
    assert project.is_dirty
    assert [event.data.get("action") for event in events] == ["updated_transform"]
    assert events[0].data.get("kind") == "port"
    assert events[0].data.get("key") == 2
    assert history._undo_stack[-1]._fields == ["_ports"]


def test_update_transform_building_fractional_preserves_fields(placement_setup):
    """Building update preserves type, province, state, and review."""
    controller, project, history = placement_setup
    building_id, _ = _seed_transform_records(project)
    events = _placement_events(project.event_bus)

    changed = controller.update_transform(
        "building", building_id, x=9.25, y=-1.5, rotation=270.75, height=3.125
    )

    assert changed is True
    record = project.map_placement_mgr.get_building(building_id)
    assert (record.x, record.y, record.rotation, record.height) == (9.25, -1.5, 270.75, 3.125)
    assert isinstance(record.x, float)
    assert record.province_id == 3
    assert record.building_type == "arms_factory"
    assert record.state_id == 5
    assert record.provenance == "generated"
    assert record.review_status == "unreviewed"
    assert project.is_dirty
    assert events[0].data.get("action") == "updated_transform"
    assert events[0].data.get("kind") == "building"
    assert events[0].data.get("key") == building_id
    assert history._undo_stack[-1]._fields == ["_buildings"]


def test_update_transform_weather_fractional_preserves_fields(placement_setup):
    """Weather update preserves region, size, kind, and review."""
    controller, project, history = placement_setup
    _, weather_id = _seed_transform_records(project)
    events = _placement_events(project.event_bus)

    changed = controller.update_transform(
        "weather", weather_id, x=-0.5, y=0.75, rotation=10.125, height=20.5
    )

    assert changed is True
    record = project.map_placement_mgr.get_weather(weather_id)
    assert (record.x, record.y, record.rotation, record.height) == (-0.5, 0.75, 10.125, 20.5)
    assert isinstance(record.height, float)
    assert record.region_id == 7
    assert record.size == "large"
    assert record.kind == "storm"
    assert record.provenance == "fallback"
    assert record.review_status == "unreviewed"
    assert project.is_dirty
    assert events[0].data.get("action") == "updated_transform"
    assert events[0].data.get("kind") == "weather"
    assert events[0].data.get("key") == weather_id
    assert history._undo_stack[-1]._fields == ["_weather"]


def test_update_transform_partial_fields_keep_remainder(placement_setup):
    """Omitted fields keep their current fractional values."""
    controller, project, history = placement_setup
    building_id, _ = _seed_transform_records(project)

    assert controller.update_transform("slot", (1, 0), x=99.5) is True
    slot = project.map_placement_mgr.get_province_slot(1, 0)
    assert slot.x == 99.5
    assert slot.y == 20.25
    assert slot.rotation == 30.5
    assert slot.height == 2.75
    assert slot.meaning == "capital"

    assert controller.update_transform("building", building_id, rotation=1.25) is True
    building = project.map_placement_mgr.get_building(building_id)
    assert building.x == 1.25
    assert building.y == 2.5
    assert building.rotation == 1.25
    assert building.height == 0.5
    assert building.building_type == "arms_factory"


def test_update_transform_noop_leaves_observables_unchanged(placement_setup):
    """Equal-value updates return False without dirty, event, or history."""
    controller, project, history = placement_setup
    _seed_transform_records(project)
    events = _placement_events(project.event_bus)

    assert controller.update_transform(
        "slot", (1, 0), x=10.5, y=20.25, rotation=30.5, height=2.75
    ) is False
    assert controller.update_transform("slot", (1, 0)) is False
    assert controller.update_transform(
        "port", 2, x=-4.5, y=8.25, rotation=15.5, height=3.5
    ) is False
    assert not project.is_dirty
    assert events == []
    assert not history.can_undo

    assert controller.update_transform("slot", (1, 0), x=11.5) is True
    assert project.is_dirty
    depth = len(history._undo_stack)
    event_count = len(events)
    assert controller.update_transform("slot", (1, 0), x=11.5) is False
    assert project.is_dirty
    assert len(history._undo_stack) == depth
    assert len(events) == event_count


def test_reset_transform_neutral_preserves_position_and_fields(placement_setup):
    """Neutral reset keeps x/y, zeroes rotation/height, preserves metadata."""
    controller, project, history = placement_setup
    building_id, weather_id = _seed_transform_records(project)
    events = _placement_events(project.event_bus)

    assert controller.reset_transform("slot", (1, 0)) is True
    slot = project.map_placement_mgr.get_province_slot(1, 0)
    assert (slot.x, slot.y, slot.rotation, slot.height) == (10.5, 20.25, 0.0, 0.0)
    assert slot.meaning == "capital"
    assert slot.provenance == "authored"
    assert slot.review_status == "reviewed"

    assert controller.reset_transform("port", 2) is True
    port = project.map_placement_mgr.get_port(2)
    assert (port.x, port.y, port.rotation, port.height) == (-4.5, 8.25, 0.0, 0.0)
    assert port.sea_province == 9
    assert port.provenance == "imported"
    assert port.review_status == "accepted"

    assert controller.reset_transform("building", building_id) is True
    building = project.map_placement_mgr.get_building(building_id)
    assert (building.x, building.y) == (1.25, 2.5)
    assert (building.rotation, building.height) == (0.0, 0.0)
    assert building.building_type == "arms_factory"
    assert building.state_id == 5
    assert building.provenance == "generated"

    assert controller.reset_transform("weather", weather_id) is True
    weather = project.map_placement_mgr.get_weather(weather_id)
    assert (weather.x, weather.y) == (100.125, -50.75)
    assert (weather.rotation, weather.height) == (0.0, 0.0)
    assert weather.size == "large"
    assert weather.kind == "storm"

    assert project.is_dirty
    assert [event.data.get("action") for event in events] == ["reset_transform"] * 4
    assert [event.data.get("kind") for event in events] == ["slot", "port", "building", "weather"]
    assert [event.data.get("key") for event in events] == [(1, 0), 2, building_id, weather_id]
    assert len(history._undo_stack) == 4
    assert history._undo_stack[0]._fields == ["_slots"]
    assert history._undo_stack[1]._fields == ["_ports"]
    assert history._undo_stack[2]._fields == ["_buildings"]
    assert history._undo_stack[3]._fields == ["_weather"]


def test_reset_transform_noop_when_already_neutral(placement_setup):
    """Resetting a neutral transform returns False without side effects."""
    controller, project, history = placement_setup
    project.map_placement_mgr.set_province_slot(
        1, 1, x=5.5, y=6.5, rotation=0.0, height=0.0,
        meaning="unit", provenance="authored", review_status="reviewed",
    )
    events = _placement_events(project.event_bus)

    assert controller.reset_transform("slot", (1, 1)) is False
    assert not project.is_dirty
    assert events == []
    assert not history.can_undo


def test_update_and_reset_unknown_kind_rejected_without_mutation(placement_setup):
    """Unknown kinds raise ValueError without dirty, event, or history."""
    controller, project, history = placement_setup
    _seed_transform_records(project)
    events = _placement_events(project.event_bus)
    before = project.map_placement_mgr.to_dict()

    with pytest.raises(ValueError):
        controller.update_transform("city", (1, 0), x=1.0)
    with pytest.raises(ValueError):
        controller.reset_transform("city", (1, 0))
    with pytest.raises(ValueError):
        controller.update_transform("SLOT", (1, 0), x=1.0)
    with pytest.raises(ValueError):
        controller.reset_transform("", 2)

    assert project.map_placement_mgr.to_dict() == before
    assert not project.is_dirty
    assert events == []
    assert not history.can_undo


def test_update_and_reset_missing_record_rejected_without_mutation(placement_setup):
    """Missing records raise KeyError and malformed slot keys ValueError."""
    controller, project, history = placement_setup
    building_id, weather_id = _seed_transform_records(project)
    events = _placement_events(project.event_bus)
    before = project.map_placement_mgr.to_dict()

    with pytest.raises(KeyError):
        controller.update_transform("slot", (99, 0), x=1.0)
    with pytest.raises(KeyError):
        controller.reset_transform("slot", (99, 0))
    with pytest.raises(KeyError):
        controller.update_transform("port", 99, x=1.0)
    with pytest.raises(KeyError):
        controller.reset_transform("port", 99)
    with pytest.raises(KeyError):
        controller.update_transform("building", 999, x=1.0)
    with pytest.raises(KeyError):
        controller.reset_transform("building", 999)
    with pytest.raises(KeyError):
        controller.update_transform("weather", 999, x=1.0)
    with pytest.raises(KeyError):
        controller.reset_transform("weather", 999)
    with pytest.raises(ValueError):
        controller.update_transform("slot", 1, x=1.0)
    with pytest.raises(ValueError):
        controller.reset_transform("slot", (1, 0, 2))
    with pytest.raises(ValueError):
        controller.reset_transform("slot", "bad")

    assert project.map_placement_mgr.to_dict() == before
    assert project.map_placement_mgr.get_province_slot(1, 0).x == 10.5
    assert project.map_placement_mgr.get_building(building_id).x == 1.25
    assert project.map_placement_mgr.get_weather(weather_id).x == 100.125
    assert not project.is_dirty
    assert events == []
    assert not history.can_undo


def test_update_transform_invalid_coordinates_rejected_without_mutation(placement_setup):
    """Bool, string, and non-finite coordinates raise ValueError cleanly."""
    controller, project, history = placement_setup
    _seed_transform_records(project)
    events = _placement_events(project.event_bus)
    before = project.map_placement_mgr.to_dict()

    with pytest.raises(ValueError):
        controller.update_transform("slot", (1, 0), x=True)
    with pytest.raises(ValueError):
        controller.update_transform("slot", (1, 0), y="12.5")
    with pytest.raises(ValueError):
        controller.update_transform("port", 2, rotation=float("inf"))
    with pytest.raises(ValueError):
        controller.update_transform("port", 2, height=float("nan"))
    with pytest.raises(ValueError):
        controller.update_transform("building", 1, x=float("-inf"))
    with pytest.raises(ValueError):
        controller.update_transform("weather", 1, rotation=False)

    assert project.map_placement_mgr.to_dict() == before
    assert not project.is_dirty
    assert events == []
    assert not history.can_undo


def test_update_transform_snapshot_scope_and_event_metadata(placement_setup):
    """Each kind snapshots only its own collection with stable metadata."""
    controller, project, history = placement_setup
    building_id, weather_id = _seed_transform_records(project)
    events = _placement_events(project.event_bus)

    assert controller.update_transform("slot", (1, 0), x=11.5) is True
    assert controller.update_transform("port", 2, x=11.5) is True
    assert controller.update_transform("building", building_id, x=11.5) is True
    assert controller.update_transform("weather", weather_id, x=11.5) is True

    assert [stack._fields for stack in history._undo_stack] == [
        ["_slots"], ["_ports"], ["_buildings"], ["_weather"]
    ]
    assert [(event.data.get("kind"), event.data.get("key")) for event in events] == [
        ("slot", (1, 0)), ("port", 2),
        ("building", building_id), ("weather", weather_id),
    ]
    assert all(event.data.get("action") == "updated_transform" for event in events)


def test_update_transform_undo_redo_restores_exact_state(placement_setup):
    """Undo and redo restore exact manager state for updates."""
    controller, project, history = placement_setup
    building_id, weather_id = _seed_transform_records(project)
    mgr = project.map_placement_mgr
    before = mgr.to_dict()

    assert controller.update_transform("slot", (1, 0), x=99.25, rotation=77.5) is True
    assert controller.update_transform("port", 2, y=-99.75, height=8.5) is True
    assert controller.update_transform(
        "building", building_id, x=5.5, y=6.5, rotation=7.5, height=8.5
    ) is True
    assert controller.update_transform("weather", weather_id, rotation=33.33) is True
    after = mgr.to_dict()
    assert after != before
    assert mgr.get_province_slot(1, 0).meaning == "capital"
    assert mgr.get_port(2).sea_province == 9
    assert mgr.get_building(building_id).building_type == "arms_factory"
    assert mgr.get_weather(weather_id).size == "large"

    assert history.undo()
    assert mgr.get_weather(weather_id).to_dict() == [
        record.to_dict() for record in [mgr.get_weather(weather_id)]
    ][0]
    assert history.undo()
    assert history.undo()
    assert history.undo()
    assert mgr.to_dict() == before
    assert mgr.get_province_slot(1, 0).x == 10.5
    assert mgr.get_port(2).y == 8.25
    assert mgr.get_building(building_id).rotation == 90.5
    assert mgr.get_weather(weather_id).rotation == 180.25

    assert history.redo()
    assert history.redo()
    assert history.redo()
    assert history.redo()
    assert mgr.to_dict() == after
    assert mgr.get_province_slot(1, 0).x == 99.25
    assert mgr.get_port(2).y == -99.75
    assert mgr.get_building(building_id).x == 5.5
    assert mgr.get_weather(weather_id).rotation == 33.33


def test_reset_transform_undo_redo_restores_exact_state(placement_setup):
    """Undo and redo restore exact manager state for neutral resets."""
    controller, project, history = placement_setup
    building_id, weather_id = _seed_transform_records(project)
    mgr = project.map_placement_mgr
    before = mgr.to_dict()

    assert controller.reset_transform("slot", (1, 0)) is True
    assert controller.reset_transform("building", building_id) is True
    after = mgr.to_dict()
    assert mgr.get_province_slot(1, 0).rotation == 0.0
    assert mgr.get_building(building_id).height == 0.0
    assert mgr.get_province_slot(1, 0).x == 10.5
    assert mgr.get_building(building_id).x == 1.25

    assert history.undo()
    assert mgr.get_building(building_id).rotation == 90.5
    assert mgr.get_province_slot(1, 0).rotation == 0.0
    assert history.undo()
    assert mgr.to_dict() == before

    assert history.redo()
    assert history.redo()
    assert mgr.to_dict() == after
    assert mgr.get_weather(weather_id).rotation == 180.25
