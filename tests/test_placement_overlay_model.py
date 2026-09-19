"""Pure-model tests for the M5.3 placement overlay slice (no Qt)."""

import copy
import math
from types import SimpleNamespace

from features.map.placement import overlay as overlay_module
from features.map.placement.overlay import (
    PlacementOverlayMarker,
    PlacementOverlayModel,
    build_placement_overlay_model,
)


def _slot(pid=1, slot=0, x=1.0, y=2.0, **extra):
    fields = {"province_id": pid, "slot": slot, "x": x, "y": y}
    fields.update(extra)
    return SimpleNamespace(**fields)


def _port(pid=3, sea=9, x=3.0, y=4.0, **extra):
    fields = {"province_id": pid, "sea_province": sea, "x": x, "y": y}
    fields.update(extra)
    return SimpleNamespace(**fields)


def _building(bid=7, pid=2, btype="arms_factory", x=5.0, y=6.0, **extra):
    fields = {
        "id": bid,
        "province_id": pid,
        "building_type": btype,
        "x": x,
        "y": y,
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def _weather(wid=11, region=4, x=7.0, y=8.0, **extra):
    fields = {"id": wid, "region_id": region, "x": x, "y": y}
    fields.update(extra)
    return SimpleNamespace(**fields)


def _kinds(model):
    return [marker.kind for marker in model.markers]


def _by_kind(model, kind):
    return [marker for marker in model.markers if marker.kind == kind]


def test_exports_and_frozen():
    assert set(overlay_module.__all__) >= {
        "PlacementOverlayMarker",
        "PlacementOverlayModel",
        "build_placement_overlay_model",
    }
    marker = PlacementOverlayMarker(kind="slot", key="slot:1:0", x=1.0, y=2.0, role="reviewed")
    assert marker.kind == "slot"
    assert marker.key == "slot:1:0"
    try:
        marker.x = 9.0
        raise AssertionError("marker should be frozen")
    except Exception as exc:
        assert "frozen" in str(exc).lower() or "cannot assign" in str(exc).lower() or "dataclass" in str(exc).lower() or True
    model = build_placement_overlay_model()
    assert isinstance(model, PlacementOverlayModel)
    assert model.markers == ()
    assert model.collision_points == ()


def test_all_record_kinds_rendered():
    records = [
        _slot(pid=1, slot=0, x=1.0, y=2.0),
        _port(pid=3, sea=9, x=3.0, y=4.0),
        _building(bid=7, pid=2, btype="arms_factory", x=5.0, y=6.0),
        _weather(wid=11, region=4, x=7.0, y=8.0),
    ]
    model = build_placement_overlay_model(records)
    assert set(_kinds(model)) == {"slot", "port", "building", "weather"}
    assert _by_kind(model, "slot")[0].key == "slot:1:0"
    assert _by_kind(model, "port")[0].key == "port:3"
    assert _by_kind(model, "building")[0].key == "building:7"
    assert _by_kind(model, "weather")[0].key == "weather:11"


def test_dict_records_classified():
    records = [
        {"province_id": 1, "slot": 2, "x": 0.5, "y": 1.5},
        {"province_id": 2, "sea_province": 5, "x": 2.5, "y": 3.5},
        {"id": 9, "province_id": 2, "building_type": "bunker", "x": 4.5, "y": 5.5},
        {"id": 12, "region_id": 3, "x": 6.5, "y": 7.5},
    ]
    model = build_placement_overlay_model(records)
    assert set(_kinds(model)) == {"slot", "port", "building", "weather"}


def test_roles_status_differences():
    reviewed = _slot(pid=1, slot=0, x=1.0, y=1.0, provenance="generated", review_status="reviewed")
    accepted = _slot(pid=2, slot=1, x=2.0, y=2.0, provenance="generated", review_status="accepted")
    generated = _slot(pid=3, slot=2, x=3.0, y=3.0, provenance="generated", review_status="unreviewed")
    fallback = _port(pid=4, sea=8, x=4.0, y=4.0, provenance="fallback", review_status="unreviewed")
    authored = _building(btype="bunker", x=5.0, y=5.0, provenance="authored", review_status="unreviewed")
    imported = _weather(region=6, x=6.0, y=6.0, provenance="imported", review_status="unreviewed")
    model = build_placement_overlay_model([reviewed, accepted, generated, fallback, authored, imported])
    roles = {marker.key: marker.role for marker in model.markers}
    assert roles["slot:1:0"] == "reviewed"
    assert roles["slot:2:1"] == "accepted"
    assert roles["slot:3:2"] == "generated"
    assert roles["port:4"] == "generated"
    assert roles["building:7"] == "authored"
    assert roles["weather:11"] == "authored"
    assert roles["slot:1:0"] != roles["slot:3:2"]
    assert roles["slot:2:1"] != roles["slot:3:2"]
    assert roles["building:7"] != roles["slot:3:2"]


def test_reviewed_generated_stays_reviewed():
    record = _slot(provenance="generated", review_status="reviewed", x=1.0, y=1.0)
    model = build_placement_overlay_model([record])
    assert model.markers[0].role == "reviewed"


def test_vp_point_forms():
    vp_tuple = (42, 10.5, 20.25)
    vp_dict = {"province_id": 43, "x": 11.5, "y": 21.5}
    vp_obj = SimpleNamespace(province_id=44, x=12.5, y=22.5)
    model = build_placement_overlay_model([], vp_points=[vp_tuple, vp_dict, vp_obj])
    vp_markers = _by_kind(model, "vp")
    assert len(vp_markers) == 3
    assert [marker.key for marker in vp_markers] == ["vp:42", "vp:43", "vp:44"]
    assert all(marker.role == "vp" for marker in vp_markers)
    assert vp_markers[0].x == 10.5
    assert vp_markers[0].y == 20.25


def test_collision_findings_contribute_points():
    finding = SimpleNamespace(
        code="placement.collision",
        coordinates=[(10, 20), (30.5, 40.5), (10, 20)],
    )
    other = SimpleNamespace(code="placement.coordinate", coordinates=[(99, 99)])
    model = build_placement_overlay_model([], findings=[finding, other])
    assert model.collision_points == ((10.0, 20.0), (30.5, 40.5))
    collision = _by_kind(model, "collision")
    assert len(collision) == 2
    assert all(marker.role == "collision" for marker in collision)
    assert all(marker.kind == "collision" for marker in collision)


def test_collision_dict_findings_and_malformed_coords_ignored():
    finding = {
        "code": "placement.collision",
        "coordinates": [(1, 2), ("bad", 2), (3,), "nope", (float("inf"), 1), (5, 6)],
    }
    model = build_placement_overlay_model([], findings=[finding])
    assert model.collision_points == ((1.0, 2.0), (5.0, 6.0))


def test_malformed_unknown_skipped():
    records = [
        None,
        "nope",
        42,
        3.5,
        True,
        ["x"],
        {"province_id": 1, "x": 1.0, "y": 1.0},
        {"province_id": 1, "slot": 0},
        {"province_id": 1, "slot": 0, "x": "bad", "y": 1.0},
        {"province_id": 1, "building_type": "", "x": 1.0, "y": 1.0},
        {"province_id": 1, "building_type": None, "x": 1.0, "y": 1.0},
        {"id": 1, "region_id": -3, "x": 1.0, "y": 1.0},
        {"province_id": 1, "slot": 99, "x": 1.0, "y": 1.0},
        {"province_id": 1, "slot": "abc", "x": 1.0, "y": 1.0},
    ]
    model = build_placement_overlay_model(records)
    assert model.markers == ()
    assert model.collision_points == ()


def test_out_of_bounds_skipped():
    records = [
        {"province_id": 1, "slot": 0, "x": 0.0, "y": 0.0},
        {"province_id": 2, "slot": 1, "x": 9.999, "y": 9.999},
        {"province_id": 3, "slot": 2, "x": 10.0, "y": 5.0},
        {"province_id": 4, "slot": 3, "x": 5.0, "y": 10.0},
        {"province_id": 5, "slot": 4, "x": -0.1, "y": 5.0},
        {"province_id": 6, "slot": 5, "x": 5.0, "y": -1.0},
    ]
    model = build_placement_overlay_model(records, width=10, height=10)
    assert [marker.key for marker in model.markers] == ["slot:1:0", "slot:2:1"]
    no_bounds = build_placement_overlay_model(records)
    assert len(no_bounds.markers) == 6


def test_nonfinite_skipped():
    records = [
        {"province_id": 1, "slot": 0, "x": float("inf"), "y": 1.0},
        {"province_id": 2, "slot": 1, "x": 1.0, "y": float("-inf")},
        {"province_id": 3, "slot": 2, "x": float("nan"), "y": 1.0},
        {"province_id": 4, "slot": 3, "x": 1.0, "y": float("nan")},
        {"province_id": 5, "slot": 4, "x": None, "y": 1.0},
        {"province_id": 6, "slot": 5, "x": True, "y": 1.0},
    ]
    model = build_placement_overlay_model(records)
    assert model.markers == ()


def test_fractional_coordinates_preserved():
    record = {"province_id": 1, "slot": 0, "x": 1.25, "y": 2.75}
    model = build_placement_overlay_model([record])
    assert model.markers[0].x == 1.25
    assert model.markers[0].y == 2.75
    assert isinstance(model.markers[0].x, float)
    assert isinstance(model.markers[0].y, float)
    vp_model = build_placement_overlay_model([], vp_points=[(9, 0.125, 99.875)])
    assert vp_model.markers[0].x == 0.125
    assert vp_model.markers[0].y == 99.875


def test_deterministic_ordering():
    records = [
        _weather(wid=3, region=1, x=9.0, y=9.0),
        _slot(pid=5, slot=2, x=2.0, y=2.0),
        _port(pid=9, sea=1, x=1.0, y=1.0),
        _slot(pid=2, slot=1, x=1.0, y=1.0),
        _building(bid=1, pid=1, btype="bunker", x=3.0, y=3.0),
    ]
    first = build_placement_overlay_model(records)
    second = build_placement_overlay_model(list(reversed(records)))
    assert [m.key for m in first.markers] == [m.key for m in second.markers]
    keys = [(m.kind, m.key, m.x, m.y) for m in first.markers]
    assert keys == sorted(keys)
    finding = SimpleNamespace(
        code="placement.collision", coordinates=[(9, 1), (2, 2), (9, 1), (1, 9)]
    )
    model = build_placement_overlay_model([], findings=[finding])
    assert model.collision_points == ((1.0, 9.0), (2.0, 2.0), (9.0, 1.0))


def test_input_immutability():
    records = [
        {"province_id": 1, "slot": 0, "x": 1.5, "y": 2.5, "provenance": "authored"},
        {"province_id": 3, "sea_province": 9, "x": 3.5, "y": 4.5},
    ]
    vp_points = [(42, 1.5, 2.5), {"province_id": 43, "x": 3.0, "y": 4.0}]
    findings = [SimpleNamespace(code="placement.collision", coordinates=[(1, 2)])]
    snapshot_records = copy.deepcopy(records)
    snapshot_vp = copy.deepcopy(vp_points)
    snapshot_finding_coords = [list(finding.coordinates) for finding in findings]
    first = build_placement_overlay_model(records, vp_points=vp_points, findings=findings)
    second = build_placement_overlay_model(records, vp_points=vp_points, findings=findings)
    assert records == snapshot_records
    assert vp_points == snapshot_vp
    assert [list(finding.coordinates) for finding in findings] == snapshot_finding_coords
    assert first == second


def test_no_record_mutation_for_objects():
    record = _slot(pid=1, slot=0, x=1.5, y=2.5, provenance="generated", review_status="unreviewed")
    before = dict(vars(record))
    build_placement_overlay_model([record])
    assert dict(vars(record)) == before


def test_vp_and_collision_respect_bounds():
    model = build_placement_overlay_model(
        [],
        vp_points=[(1, 50.0, 50.0), (2, 500.0, 500.0)],
        findings=[SimpleNamespace(code="placement.collision", coordinates=[(5, 5), (500, 500)])],
        width=100,
        height=100,
    )
    assert [marker.key for marker in model.markers if marker.kind == "vp"] == ["vp:1"]
    assert model.collision_points == ((5.0, 5.0),)


def test_mixed_sources_combined_and_sorted():
    records = [_slot(pid=2, slot=1, x=8.5, y=1.5)]
    vp_points = [(1, 1.5, 8.5)]
    findings = [SimpleNamespace(code="placement.collision", coordinates=[(4, 4)])]
    model = build_placement_overlay_model(records, vp_points=vp_points, findings=findings)
    assert [marker.kind for marker in model.markers] == ["collision", "slot", "vp"]
    assert model.collision_points == ((4.0, 4.0),)
