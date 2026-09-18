"""M5.1 authored placement model tests (no game install)."""
from __future__ import annotations

import json

import pytest

from domain.managers.map_placement import (
    AUTO_PROVENANCES,
    BuildingPlacement,
    MapPlacementManager,
    PortPlacement,
    ProvincePositionSlot,
    WeatherPosition,
)

pytestmark = pytest.mark.unit


def _populated():
    mgr = MapPlacementManager()
    mgr.set_province_slot(
        5, 2, 1.5, 2.25, rotation=45.5, height=3.125,
        meaning="city", provenance="imported",
    )
    mgr.set_province_slot(5, 0, 0.5, 0.5)
    mgr.add_building(
        5, "bunker", 10.75, 20.5, rotation=90.0, height=1.5,
        state_id=1, provenance="authored",
    )
    mgr.add_building(3, "arms_factory", 4.0, 6.0)
    mgr.set_port(7, 3.5, 4.5, sea_province=9, provenance="authored")
    mgr.add_weather(2, 100.125, 200.5, size="small", kind="winter")
    mgr.add_weather(1, 1.0, 2.0)
    return mgr


def test_crud_and_counts():
    mgr = MapPlacementManager()
    assert mgr.count() == 0
    mgr.set_province_slot(1, 0, 0.5, 0.5)
    assert mgr.get_province_slot(1, 0) is not None
    assert mgr.get_province_slot(1, 1) is None
    mgr.set_province_slot(1, 0, 0.75, 0.5)
    assert mgr.count_slots() == 1
    assert mgr.get_province_slot(1, 0).x == 0.75
    assert mgr.remove_province_slot(1, 0) is True
    assert mgr.remove_province_slot(1, 0) is False

    bid = mgr.add_building(2, "bunker", 1.0, 1.0)
    assert mgr.get_building(bid).building_type == "bunker"
    mgr.update_building(bid, x=2.0)
    assert mgr.get_building(bid).x == 2.0
    assert mgr.remove_building(bid) is True
    assert mgr.get_building(bid) is None

    mgr.set_port(4, 1.0, 2.0, sea_province=6)
    assert mgr.get_port(4).sea_province == 6
    assert mgr.remove_port(4) is True
    assert mgr.remove_port(4) is False

    wid = mgr.add_weather(1, 5.0, 5.0)
    assert mgr.get_weather(wid).region_id == 1
    mgr.update_weather(wid, size="large")
    assert mgr.get_weather(wid).size == "large"
    assert mgr.remove_weather(wid) is True

    assert mgr.count() == 0
    mgr.clear()
    assert mgr.count() == 0


def test_slot_index_range():
    mgr = MapPlacementManager()
    for slot in range(6):
        mgr.set_province_slot(1, slot, float(slot), 0.0)
    assert mgr.count_slots() == 6
    with pytest.raises(ValueError):
        mgr.set_province_slot(1, 6, 0.0, 0.0)
    with pytest.raises(ValueError):
        mgr.set_province_slot(1, -1, 0.0, 0.0)
    with pytest.raises(ValueError):
        mgr.set_province_slot(0, 0, 0.0, 0.0)


def test_round_trip():
    mgr = _populated()
    payload = mgr.to_dict()
    clone = MapPlacementManager()
    clone.from_dict(payload)
    assert clone.to_dict() == payload
    assert clone.count() == mgr.count()
    assert clone._next_building_id == mgr._next_building_id
    assert clone._next_weather_id == mgr._next_weather_id


def test_round_trip_through_json():
    mgr = _populated()
    payload = json.loads(json.dumps(mgr.to_dict()))
    clone = MapPlacementManager()
    clone.from_dict(payload)
    assert clone.to_dict() == mgr.to_dict()


def test_floats_preserved_without_integer_conversion():
    mgr = MapPlacementManager()
    mgr.set_province_slot(1, 3, 123.456789, 0.1, rotation=0.3, height=2.675)
    bid = mgr.add_building(2, "radar_station", 7.875, 9.0625, height=0.125)
    mgr.set_port(3, 5.5, 6.25, rotation=12.75, height=0.5)
    wid = mgr.add_weather(1, 300.333, 400.666)
    slot = mgr.get_province_slot(1, 3)
    assert slot.x == 123.456789
    assert slot.rotation == 0.3
    assert slot.height == 2.675
    assert all(
        isinstance(value, float)
        for value in (slot.x, slot.y, slot.rotation, slot.height)
    )
    building = mgr.get_building(bid)
    assert building.x == 7.875
    assert building.height == 0.125
    clone = MapPlacementManager()
    clone.from_dict(json.loads(json.dumps(mgr.to_dict())))
    assert clone.get_province_slot(1, 3).x == 123.456789
    assert clone.get_building(bid).x == 7.875
    assert clone.get_port(3).rotation == 12.75
    assert clone.get_weather(wid).x == 300.333
    whole = MapPlacementManager()
    whole.set_province_slot(9, 1, 4, 8)
    record = whole.get_province_slot(9, 1)
    assert record.x == 4.0 and isinstance(record.x, float)


def test_unknown_provenance_and_review_rejected():
    mgr = MapPlacementManager()
    with pytest.raises(ValueError):
        mgr.set_province_slot(1, 0, 0.0, 0.0, provenance="draft")
    with pytest.raises(ValueError):
        mgr.set_province_slot(1, 0, 0.0, 0.0, review_status="pending")
    with pytest.raises(ValueError):
        mgr.add_building(1, "bunker", 0.0, 0.0, provenance="auto")
    with pytest.raises(ValueError):
        mgr.set_port(1, 0.0, 0.0, review_status="approved")
    with pytest.raises(ValueError):
        mgr.add_weather(1, 0.0, 0.0, provenance="generated", review_status="x")
    with pytest.raises(ValueError):
        ProvincePositionSlot(
            province_id=1, slot=0, x=0.0, y=0.0, provenance="nope"
        )
    with pytest.raises(ValueError):
        BuildingPlacement(
            id=1, province_id=1, building_type="bunker", x=0.0, y=0.0,
            review_status="nope",
        )


def test_generated_and_fallback_require_explicit_review():
    mgr = MapPlacementManager()
    for provenance in ("generated", "fallback"):
        mgr.set_province_slot(10, 0, 1.0, 1.0, provenance=provenance)
        mgr.mark_slot_reviewed(10, 0, "reviewed")
        assert mgr.get_province_slot(10, 0).provenance == provenance
        assert mgr.get_province_slot(10, 0).review_status == "reviewed"
        mgr.remove_province_slot(10, 0)
        bid = mgr.add_building(11, "bunker", 1.0, 1.0, provenance=provenance)
        mgr.mark_building_reviewed(bid, "accepted")
        assert mgr.get_building(bid).provenance == provenance
        assert mgr.get_building(bid).review_status == "accepted"
        mgr.remove_building(bid)
        mgr.set_port(12, 1.0, 1.0, provenance=provenance)
        mgr.mark_port_reviewed(12, "reviewed")
        assert mgr.get_port(12).provenance == provenance
        assert mgr.get_port(12).review_status == "reviewed"
        mgr.remove_port(12)
        wid = mgr.add_weather(3, 1.0, 1.0, provenance=provenance)
        mgr.mark_weather_reviewed(wid, "accepted")
        assert mgr.get_weather(wid).provenance == provenance
        assert mgr.get_weather(wid).review_status == "accepted"
        mgr.remove_weather(wid)
    assert mgr.count() == 0


def test_generated_review_status_survives_deserialization():
    mgr = MapPlacementManager()
    payload = mgr.to_dict()
    payload["buildings"].append(
        {
            "id": 1, "province_id": 1, "building_type": "bunker",
            "x": 0.5, "y": 0.5, "provenance": "generated",
            "review_status": "reviewed",
        }
    )
    mgr.from_dict(payload)
    assert mgr.get_building(1).provenance == "generated"
    assert mgr.get_building(1).review_status == "reviewed"


def test_reauthor_then_review_is_allowed():
    mgr = MapPlacementManager()
    bid = mgr.add_building(1, "bunker", 0.5, 0.5, provenance="generated")
    mgr.update_building(bid, provenance="authored")
    mgr.mark_building_reviewed(bid, "reviewed")
    assert mgr.get_building(bid).review_status == "reviewed"
    mgr.mark_building_reviewed(bid, "accepted")
    assert mgr.get_building(bid).review_status == "accepted"
    mgr.update_building(bid, provenance="fallback")
    assert mgr.get_building(bid).review_status == "unreviewed"


def test_authored_review_flow():
    mgr = MapPlacementManager()
    mgr.set_province_slot(1, 1, 2.0, 3.0, provenance="authored")
    mgr.mark_slot_reviewed(1, 1, "reviewed")
    assert mgr.get_province_slot(1, 1).review_status == "reviewed"
    with pytest.raises(KeyError):
        mgr.mark_slot_reviewed(99, 1, "reviewed")
    with pytest.raises(KeyError):
        mgr.mark_building_reviewed(999, "reviewed")
    with pytest.raises(KeyError):
        mgr.mark_port_reviewed(999, "reviewed")
    with pytest.raises(KeyError):
        mgr.mark_weather_reviewed(999, "reviewed")


def test_deterministic_ordering():
    mgr = MapPlacementManager()
    mgr.set_province_slot(9, 2, 0.0, 0.0)
    mgr.set_province_slot(3, 5, 0.0, 0.0)
    mgr.set_province_slot(3, 1, 0.0, 0.0)
    assert [(r.province_id, r.slot) for r in mgr.list_province_slots()] == [
        (3, 1), (3, 5), (9, 2),
    ]
    mgr.add_building(9, "bunker", 0.0, 0.0)
    mgr.add_building(3, "bunker", 0.0, 0.0)
    mgr.add_building(3, "arms_factory", 0.0, 0.0)
    assert [
        (r.province_id, r.building_type) for r in mgr.list_buildings()
    ] == [(3, "arms_factory"), (3, "bunker"), (9, "bunker")]
    mgr.set_port(9, 0.0, 0.0)
    mgr.set_port(2, 0.0, 0.0)
    assert [r.province_id for r in mgr.list_ports()] == [2, 9]
    mgr.add_weather(2, 0.0, 0.0)
    mgr.add_weather(1, 1.0, 1.0)
    mgr.add_weather(1, 0.0, 0.0)
    assert [(r.region_id, r.id) for r in mgr.list_weather()] == [
        (1, 2), (1, 3), (2, 1),
    ]
    payload = mgr.to_dict()
    assert [r["province_id"] for r in payload["ports"]] == [2, 9]
    assert [(r["region_id"], r["id"]) for r in payload["weather"]] == [
        (1, 2), (1, 3), (2, 1),
    ]


def test_drop_provinces():
    mgr = _populated()
    mgr.set_port(8, 1.0, 1.0)
    mgr.drop_provinces({5, 7})
    assert mgr.find_slots_by_province(5) == []
    assert mgr.find_buildings_by_province(5) == []
    assert mgr.get_port(7) is None
    assert mgr.get_port(8) is not None
    assert mgr.count_slots() == 0
    assert mgr.count_buildings() == 1
    survivors = mgr.list_buildings()
    assert [r.province_id for r in survivors] == [3]


def test_remap_provinces_drops_missing_and_zero():
    mgr = _populated()
    mgr.remap_provinces({3: 30, 5: 50, 7: 70, 9: 90, 2: 0})
    assert mgr.get_province_slot(50, 2) is not None
    assert mgr.find_buildings_by_province(30) != []
    assert mgr.get_port(70).sea_province == 90
    mgr.set_port(21, 1.0, 1.0, sea_province=22)
    mgr.remap_provinces({21: 210})
    assert mgr.get_port(210).sea_province is None
    mgr.set_province_slot(40, 0, 0.0, 0.0)
    mgr.remap_provinces({40: 0})
    assert mgr.get_province_slot(40, 0) is None


def test_state_remap_clears_instead_of_dropping():
    mgr = _populated()
    bid = next(
        r.id for r in mgr.list_buildings() if r.province_id == 5
    )
    assert mgr.get_building(bid).state_id == 1
    mgr.drop_states({1})
    assert mgr.get_building(bid).state_id is None
    assert mgr.get_building(bid) is not None
    mgr.update_building(bid, state_id=4)
    mgr.remap_states({4: 40})
    assert mgr.get_building(bid).state_id == 40
    mgr.remap_states({40: 0})
    assert mgr.get_building(bid).state_id is None
    mgr.update_building(bid, state_id=7)
    mgr.remap_states({})
    assert mgr.get_building(bid).state_id is None


def test_region_remap_drops_weather():
    mgr = _populated()
    assert mgr.count_weather() == 2
    mgr.drop_regions({2})
    assert mgr.count_weather() == 1
    assert mgr.list_weather()[0].region_id == 1
    mgr.remap_regions({1: 10})
    assert mgr.list_weather()[0].region_id == 10
    mgr.remap_regions({})
    assert mgr.count_weather() == 0


def test_remap_compact_combined():
    mgr = _populated()
    mgr.remap_compact(
        province_map={3: 30, 5: 50, 7: 70, 9: 90},
        state_map={1: 100},
        region_map={1: 10, 2: 20},
    )
    assert mgr.get_province_slot(50, 2) is not None
    assert mgr.get_port(70).sea_province == 90
    reviewed = [r for r in mgr.list_buildings() if r.province_id == 50]
    assert reviewed and reviewed[0].state_id == 100
    assert sorted(r.region_id for r in mgr.list_weather()) == [10, 20]
    mgr.remap_compact()
    assert mgr.count() == 7


def test_malformed_payload_contract_is_fail_fast():
    mgr = MapPlacementManager()
    with pytest.raises(ValueError):
        mgr.from_dict(None)
    with pytest.raises(ValueError):
        mgr.from_dict([])
    with pytest.raises(ValueError):
        mgr.from_dict({"version": 999})
    with pytest.raises(ValueError):
        mgr.from_dict({"province_slots": {}})
    with pytest.raises(ValueError):
        mgr.from_dict({"province_slots": [{"province_id": 1, "slot": 0}]})
    with pytest.raises(ValueError):
        mgr.from_dict(
            {"province_slots": [{"province_id": 1, "slot": 9, "x": 0.0, "y": 0.0}]}
        )
    with pytest.raises(ValueError):
        mgr.from_dict(
            {"buildings": [
                {"id": 1, "province_id": 1, "building_type": "bunker",
                 "x": float("nan"), "y": 0.0}
            ]}
        )
    with pytest.raises(ValueError):
        mgr.from_dict(
            {"ports": [{"province_id": 1, "x": "oops", "y": 0.0}]}
        )
    with pytest.raises(ValueError):
        mgr.from_dict(
            {"weather": [
                {"id": 1, "region_id": 1, "x": 0.0, "y": 0.0,
                 "provenance": "fallback", "review_status": "pending"}
            ]}
        )
    assert mgr.count() == 0


def test_from_dict_rejects_duplicates():
    mgr = MapPlacementManager()
    dup_slot = {"province_id": 1, "slot": 0, "x": 0.0, "y": 0.0}
    with pytest.raises(ValueError):
        mgr.from_dict({"province_slots": [dup_slot, dict(dup_slot)]})
    dup_building = {
        "id": 4, "province_id": 1, "building_type": "bunker",
        "x": 0.0, "y": 0.0,
    }
    with pytest.raises(ValueError):
        mgr.from_dict({"buildings": [dup_building, dict(dup_building)]})
    dup_port = {"province_id": 2, "x": 0.0, "y": 0.0}
    with pytest.raises(ValueError):
        mgr.from_dict({"ports": [dup_port, dict(dup_port)]})
    dup_weather = {"id": 6, "region_id": 1, "x": 0.0, "y": 0.0}
    with pytest.raises(ValueError):
        mgr.from_dict({"weather": [dup_weather, dict(dup_weather)]})
    assert mgr.count() == 0


def test_from_dict_failure_leaves_manager_unchanged():
    mgr = _populated()
    snapshot = mgr.to_dict()
    with pytest.raises(ValueError):
        mgr.from_dict(
            {"buildings": [{"id": 1, "province_id": -3, "x": 0.0, "y": 0.0}]}
        )
    assert mgr.to_dict() == snapshot


def test_unknown_extra_fields_are_ignored():
    mgr = MapPlacementManager()
    mgr.from_dict(
        {
            "province_slots": [
                {"province_id": 1, "slot": 0, "x": 0.0, "y": 0.0,
                 "notes": "extra", "legacy": 42}
            ],
            "buildings": [
                {"id": 1, "province_id": 1, "building_type": "bunker",
                 "x": 0.0, "y": 0.0, "extra": True}
            ],
            "future_section": [{"hello": "world"}],
        }
    )
    assert mgr.count_slots() == 1
    assert mgr.count_buildings() == 1


def test_id_counters_survive_round_trip_and_reject_bad_ids():
    mgr = MapPlacementManager()
    first = mgr.add_building(1, "bunker", 0.0, 0.0)
    assert first == 1
    with pytest.raises(ValueError):
        mgr.add_building(0, "bunker", 0.0, 0.0)
    assert mgr.add_building(1, "bunker", 0.0, 0.0) == 2
    with pytest.raises(ValueError):
        BuildingPlacement(
            id=0, province_id=1, building_type="bunker", x=0.0, y=0.0
        )
    with pytest.raises(ValueError):
        WeatherPosition(id=1, region_id=0, x=0.0, y=0.0)
    with pytest.raises(ValueError):
        PortPlacement(province_id=1, x=float("inf"), y=0.0)
    payload = mgr.to_dict()
    clone = MapPlacementManager()
    clone.from_dict(payload)
    assert clone.add_building(2, "bunker", 0.0, 0.0) == 3


def test_auto_provenance_constants_cover_both_values():
    assert AUTO_PROVENANCES == {"generated", "fallback"}
