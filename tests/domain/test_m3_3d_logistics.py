"""M3.3d adjacency/logistics validation slice tests (no game install)."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from domain.managers.adjacency import AdjacencyEntry, AdjacencyManager
from domain.managers.adjacency_rule import AdjacencyRule, AdjacencyRuleManager
from domain.managers.railway import RailwayEntry, RailwayManager
from domain.managers.supply_node import SupplyNode, SupplyNodeManager
from domain.logistics_exceptions import LogisticsExceptionManager
from domain.validation import FINDING_SEVERITIES, ValidationFinding
from domain.validators.logistics import CODES, validate_logistics_references

pytestmark = pytest.mark.unit


class _FakeManager:
    """Minimal duck-typed manager exposing only ``get_all()``."""

    def __init__(self, entries):
        self._entries = list(entries)

    def get_all(self):
        return list(self._entries)


def _land_2x3():
    tile = np.full((2, 3), TILE_LAND, dtype=np.uint8)
    prov = np.array([[1, 2, 3], [1, 2, 3]], dtype=np.int32)
    return tile, prov


def _coast_2x4():
    tile = np.array(
        [[TILE_LAND, TILE_LAND, TILE_SEA, TILE_SEA],
         [TILE_LAND, TILE_LAND, TILE_SEA, TILE_SEA]],
        dtype=np.uint8,
    )
    prov = np.array([[1, 1, 2, 2], [3, 3, 4, 4]], dtype=np.int32)
    return tile, prov


def _codes(findings):
    return [item.code for item in findings]


def _by_code(findings):
    grouped = {}
    for item in findings:
        grouped.setdefault(item.code, []).append(item)
    return grouped


def test_clean_data_has_no_findings():
    tile, prov = _land_2x3()
    adj = AdjacencyManager()
    adj.add(AdjacencyEntry(1, 2, "sea", through_id=-1, start_x=0, start_y=0,
                           stop_x=1, stop_y=0, rule_name="STRAIT"))
    rules = AdjacencyRuleManager()
    rules.add(AdjacencyRule(name="STRAIT", required_provinces=[1, 2], icon_province=-1))
    rail = RailwayManager()
    rail.add(2, [1, 2, 3])
    sup = SupplyNodeManager()
    sup.add(1)
    sup.add(3)
    findings = validate_logistics_references(
        prov, tile, adjacency_mgr=adj, railway_mgr=rail, supply_mgr=sup,
        adjacency_rule_mgr=rules, country_mgr=SimpleNamespace(), profile=None,
    )
    assert findings == []


def test_absent_and_empty_managers_are_noop():
    tile, prov = _land_2x3()
    assert validate_logistics_references(prov, tile) == []
    assert validate_logistics_references(
        prov, tile,
        adjacency_mgr=AdjacencyManager(),
        railway_mgr=RailwayManager(),
        supply_mgr=SupplyNodeManager(),
        adjacency_rule_mgr=AdjacencyRuleManager(),
    ) == []


def test_adjacency_unknown_endpoints_and_self_loop():
    tile, prov = _land_2x3()
    adj = AdjacencyManager()
    adj.add(AdjacencyEntry(1, 99, "sea"))
    adj.add(AdjacencyEntry(2, 2, "sea"))
    adj.add(AdjacencyEntry(3, 1, "sea", through_id=50))
    findings = validate_logistics_references(prov, tile, adjacency_mgr=adj)
    assert _codes(findings) == ["logistics.adjacency_endpoint"]
    item = findings[0]
    assert item.severity == "error"
    assert tuple(item.affected_ids) == (2, 50, 99)
    assert "unknown" in item.evidence
    assert "self-loop" in item.evidence


def test_adjacency_illegal_type_and_impassable_contract():
    tile, prov = _land_2x3()
    adj = AdjacencyManager()
    adj.add(AdjacencyEntry(1, 2, "canal"))
    adj.add(AdjacencyEntry(2, 3, "impassable", through_id=1, start_x=0,
                           start_y=0, stop_x=1, stop_y=0, rule_name="X"))
    findings = validate_logistics_references(prov, tile, adjacency_mgr=adj)
    assert _codes(findings) == ["logistics.adjacency_endpoint"]
    item = findings[0]
    assert item.severity == "error"
    assert tuple(item.affected_ids) == (1, 2, 3)
    assert "illegal type" in item.evidence
    assert "through_id -1" in item.evidence
    assert "coordinates -1" in item.evidence
    assert "must not name rule" in item.evidence


def test_adjacency_unknown_rule_and_bad_coordinates():
    tile, prov = _land_2x3()
    adj = AdjacencyManager()
    adj.add(AdjacencyEntry(1, 2, "sea", rule_name="NOPE"))
    adj.add(AdjacencyEntry(2, 3, "sea", start_x=0, start_y=-1))
    adj.add(AdjacencyEntry(1, 3, "sea", start_x=9, start_y=9))
    rules = AdjacencyRuleManager()
    rules.add(AdjacencyRule(name="KNOWN"))
    findings = validate_logistics_references(
        prov, tile, adjacency_mgr=adj, adjacency_rule_mgr=rules)
    assert _codes(findings) == ["logistics.adjacency_endpoint"]
    item = findings[0]
    assert tuple(item.affected_ids) == (1, 2, 3)
    assert "unknown" in item.evidence
    assert "partially unset" in item.evidence
    assert "out of bounds" in item.evidence
    assert (9, 9) not in tuple(item.coordinates)
    assert tuple(item.coordinates) == ((0, 0), (1, 0), (2, 0))


def test_mapping_entries_are_supported():
    tile, prov = _land_2x3()
    adj = _FakeManager([{
        "from_id": 1, "to_id": 99, "type": "sea", "through_id": -1,
        "start_x": -1, "start_y": -1, "stop_x": -1, "stop_y": -1,
        "rule_name": "",
    }])
    findings = validate_logistics_references(prov, tile, adjacency_mgr=adj)
    assert _codes(findings) == ["logistics.adjacency_endpoint"]
    assert tuple(findings[0].affected_ids) == (99,)


def test_adjacency_rule_missing_provinces_and_icon():
    tile, prov = _land_2x3()
    rules = AdjacencyRuleManager()
    rules.add(AdjacencyRule(name="GOOD", required_provinces=[1, 2]))
    rules.add(AdjacencyRule(name="BAD", required_provinces=[2, 99], icon_province=77))
    rules.add(AdjacencyRule(name="ODD"))
    findings = validate_logistics_references(prov, tile, adjacency_rule_mgr=rules)
    assert _codes(findings) == ["logistics.adjacency_rule"]
    item = findings[0]
    assert item.severity == "error"
    assert tuple(item.affected_ids) == (77, 99)
    assert "unknown province 99" in item.evidence
    assert "icon province 77 is unknown" in item.evidence


def test_railway_route_problems():
    tile, prov = _coast_2x4()
    adj = AdjacencyManager()
    adj.add(AdjacencyEntry(1, 3, "impassable"))
    rail = _FakeManager([
        RailwayEntry(level=2, province_ids=[1]),
        RailwayEntry(level=9, province_ids=[1, 3]),
        RailwayEntry(level=1, province_ids=[1, 99]),
        RailwayEntry(level=1, province_ids=[1, 4]),
        RailwayEntry(level=1, province_ids=[3, 4]),
        RailwayEntry(level=1, province_ids=[2, 2]),
        RailwayEntry(level=1, province_ids=[1, 3]),
    ])
    findings = validate_logistics_references(prov, tile, adjacency_mgr=adj, railway_mgr=rail)
    assert _codes(findings) == ["logistics.railway_route", "logistics.graph", "logistics.duplicate_route"]
    item = _by_code(findings)["logistics.railway_route"][0]
    assert item.severity == "error"
    assert tuple(item.affected_ids) == (1, 2, 3, 4, 99)
    assert "fewer than two" in item.evidence
    assert "illegal level 9" in item.evidence
    assert "unknown province 99" in item.evidence
    assert "not adjacent" in item.evidence
    assert "impassable" in item.evidence
    assert tuple(item.coordinates) == ((0, 0), (0, 1), (2, 0), (2, 1))
    dup = _by_code(findings)["logistics.duplicate_route"][0]
    assert "entries=1,6" in dup.evidence
    graph = _by_code(findings)["logistics.graph"][0]
    assert graph.severity == "warning"


def test_railway_through_water_reports_surface():
    tile, prov = _coast_2x4()
    rail = _FakeManager([RailwayEntry(level=1, province_ids=[3, 4])])
    findings = validate_logistics_references(prov, tile, railway_mgr=rail)
    assert _codes(findings) == ["logistics.railway_route"]
    assert "surface=sea" in findings[0].evidence
    assert tuple(findings[0].affected_ids) == (4,)


def test_railway_self_loop_revisit():
    tile, prov = _land_2x3()
    rail = _FakeManager([RailwayEntry(level=1, province_ids=[2, 2])])
    findings = validate_logistics_references(prov, tile, railway_mgr=rail)
    assert _codes(findings) == ["logistics.railway_route"]
    assert "self-loop" in findings[0].evidence
    assert tuple(findings[0].affected_ids) == (2,)


def test_malformed_railway_ids_do_not_crash():
    tile, prov = _land_2x3()
    rail = _FakeManager([RailwayEntry(level=1, province_ids="12")])
    findings = validate_logistics_references(prov, tile, railway_mgr=rail)
    assert _codes(findings) == ["logistics.railway_route"]
    assert "malformed" in findings[0].evidence


def test_supply_node_problems():
    tile, prov = _land_2x3()
    sup = _FakeManager([
        SupplyNode(province_id=2, level=1),
        SupplyNode(province_id=99, level=1),
        SupplyNode(province_id=1, level=0),
    ])
    findings = validate_logistics_references(prov, tile, supply_mgr=sup)
    assert _codes(findings) == ["logistics.supply_node"]
    item = _by_code(findings)["logistics.supply_node"][0]
    assert item.severity == "error"
    assert "2 supply nodes are invalid" in item.message
    assert tuple(item.affected_ids) == (1, 99)
    assert "unknown province 99" in item.evidence
    assert "illegal level 0" in item.evidence


def test_port_flags_water_supply_and_land_icon():
    tile, prov = _coast_2x4()
    sup = SupplyNodeManager()
    sup.add(2)
    sup.add(1)
    rules = AdjacencyRuleManager()
    rules.add(AdjacencyRule(name="CANAL", required_provinces=[1, 3], icon_province=2))
    rules.add(AdjacencyRule(name="BROKEN", required_provinces=[1, 3], icon_province=1))
    findings = validate_logistics_references(
        prov, tile, supply_mgr=sup, adjacency_rule_mgr=rules)
    assert _codes(findings) == ["logistics.port", "logistics.graph"]
    item = _by_code(findings)["logistics.port"][0]
    assert item.severity == "error"
    assert tuple(item.affected_ids) == (1, 2)
    assert "sits on water" in item.evidence
    assert "not a sea province" in item.evidence


def test_graph_reports_disconnected_and_off_rail_supply():
    tile, prov = _land_2x3()
    rail = RailwayManager()
    rail.add(1, [1, 2])
    sup = SupplyNodeManager()
    sup.add(1)
    sup.add(3)
    findings = validate_logistics_references(prov, tile, railway_mgr=rail, supply_mgr=sup)
    assert _codes(findings) == ["logistics.graph"]
    item = findings[0]
    assert item.severity == "warning"
    assert item.waivable is True
    assert tuple(item.affected_ids) == (3,)
    assert "components=2" in item.evidence
    assert "off_rail_supply=3" in item.evidence


def test_duplicate_routes_both_orientations():
    tile, prov = _land_2x3()
    rail = RailwayManager()
    rail.add(1, [1, 2])
    rail.add(3, [2, 1])
    rail.add(2, [2, 3])
    findings = validate_logistics_references(prov, tile, railway_mgr=rail)
    assert _codes(findings) == ["logistics.duplicate_route"]
    item = findings[0]
    assert item.severity == "error"
    assert tuple(item.affected_ids) == (1, 2)
    assert "path=1-2" in item.evidence
    assert "occurrences=2" in item.evidence
    assert "entries=0,1" in item.evidence


def _combined_inputs():
    tile, prov = _coast_2x4()
    adj = AdjacencyManager()
    adj.add(AdjacencyEntry(1, 99, "sea"))
    rules = AdjacencyRuleManager()
    rules.add(AdjacencyRule(name="GOOD", required_provinces=[1, 2], icon_province=2))
    rules.add(AdjacencyRule(name="BAD", required_provinces=[99], icon_province=-1))
    rail = _FakeManager([
        RailwayEntry(level=1, province_ids=[1, 2]),
        RailwayEntry(level=1, province_ids=[1, 2]),
        RailwayEntry(level=9, province_ids=[1, 2]),
    ])
    sup = _FakeManager([
        SupplyNode(province_id=1, level=1),
        SupplyNode(province_id=3, level=1),
        SupplyNode(province_id=4, level=1),
        SupplyNode(province_id=99, level=1),
    ])
    return prov, tile, adj, rules, rail, sup


def _run_combined():
    prov, tile, adj, rules, rail, sup = _combined_inputs()
    return validate_logistics_references(
        prov, tile, adjacency_mgr=adj, railway_mgr=rail, supply_mgr=sup,
        adjacency_rule_mgr=rules,
        logistics_exception_mgr=LogisticsExceptionManager(),
    )


def test_combined_input_covers_all_codes_in_order():
    findings = _run_combined()
    assert _codes(findings) == list(CODES)


def test_stable_codes_and_metadata():
    findings = _run_combined()
    assert findings
    allowed = set(FINDING_SEVERITIES)
    order = []
    for item in findings:
        assert isinstance(item, ValidationFinding)
        assert item.code in CODES
        assert item.code.startswith("logistics.")
        assert item.severity in allowed
        assert item.layer == "logistics"
        assert item.message.strip()
        assert item.evidence.strip()
        assert tuple(sorted(item.affected_ids)) == tuple(item.affected_ids)
        assert tuple(sorted(item.coordinates)) == tuple(item.coordinates)
        order.append(CODES.index(item.code))
    assert order == sorted(order)
    by_code = _by_code(findings)
    for code in ("logistics.adjacency_endpoint", "logistics.adjacency_rule",
                 "logistics.railway_route", "logistics.supply_node",
                 "logistics.port", "logistics.duplicate_route"):
        assert by_code[code][0].severity == "error"
    graph = by_code["logistics.graph"][0]
    assert graph.severity == "warning"
    assert graph.waivable is True


def test_deterministic_repeatability():
    first = _run_combined()
    second = _run_combined()
    assert first == second
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]


def test_no_input_mutation():
    tile, prov = _land_2x3()
    tile_snapshot = tile.copy()
    prov_snapshot = prov.copy()
    adj = AdjacencyManager()
    adj.add(AdjacencyEntry(1, 99, "sea"))
    rules = AdjacencyRuleManager()
    rules.add(AdjacencyRule(name="BAD", required_provinces=[99], icon_province=-1))
    rail = RailwayManager()
    rail.add(1, [1, 2])
    sup = SupplyNodeManager()
    sup.add(3)
    snapshots = (adj.to_dict(), rules.to_dict(), rail.to_dict(), sup.to_dict())
    validate_logistics_references(
        prov, tile, adjacency_mgr=adj, railway_mgr=rail, supply_mgr=sup,
        adjacency_rule_mgr=rules,
    )
    np.testing.assert_array_equal(tile, tile_snapshot)
    np.testing.assert_array_equal(prov, prov_snapshot)
    assert adj.to_dict() == snapshots[0]
    assert rules.to_dict() == snapshots[1]
    assert rail.to_dict() == snapshots[2]
    assert sup.to_dict() == snapshots[3]


def test_none_province_map_keeps_structural_checks():
    rail = _FakeManager([
        RailwayEntry(level=9, province_ids=[1, 99]),
        RailwayEntry(level=1, province_ids=[5]),
    ])
    sup = _FakeManager([SupplyNode(province_id=7, level=0)])
    findings = validate_logistics_references(None, None, railway_mgr=rail, supply_mgr=sup)
    by_code = _by_code(findings)
    assert "logistics.railway_route" in by_code
    assert "logistics.supply_node" in by_code
    assert "illegal level 9" in by_code["logistics.railway_route"][0].evidence
    assert "fewer than two" in by_code["logistics.railway_route"][0].evidence
    assert "illegal level 0" in by_code["logistics.supply_node"][0].evidence
    for item in findings:
        assert "unknown" not in item.evidence
def test_wrap_horizontal_seam_disabled():
    tile = np.full((1, 3), TILE_LAND, dtype=np.uint8)
    prov = np.array([[1, 2, 3]], dtype=np.int32)
    rail = _FakeManager([RailwayEntry(level=1, province_ids=[1, 3])])
    assert validate_logistics_references(prov, tile, railway_mgr=rail) == []
    findings = validate_logistics_references(prov, tile, railway_mgr=rail, wrap_horizontal=False)
    assert _codes(findings) == ["logistics.railway_route"]
    assert "not adjacent" in findings[0].evidence
    assert validate_logistics_references(prov, tile, railway_mgr=rail, wrap_horizontal=True) == []


def test_wrap_horizontal_profile_disables_seam():
    tile = np.full((1, 3), TILE_LAND, dtype=np.uint8)
    prov = np.array([[1, 2, 3]], dtype=np.int32)
    rail = _FakeManager([RailwayEntry(level=1, province_ids=[1, 3])])
    profile = SimpleNamespace(dimensions=SimpleNamespace(wrap_horizontal=False))
    findings = validate_logistics_references(prov, tile, railway_mgr=rail, profile=profile)
    assert _codes(findings) == ["logistics.railway_route"]
    assert "not adjacent" in findings[0].evidence
    assert validate_logistics_references(prov, tile, railway_mgr=rail, profile=profile, wrap_horizontal=True) == []


def test_duplicate_unknown_routes_still_flagged():
    tile, prov = _land_2x3()
    rail = _FakeManager([
        RailwayEntry(level=1, province_ids=[99, 100]),
        RailwayEntry(level=2, province_ids=[100, 99]),
    ])
    findings = validate_logistics_references(prov, tile, railway_mgr=rail)
    by_code = _by_code(findings)
    assert "logistics.duplicate_route" in by_code
    dup = by_code["logistics.duplicate_route"][0]
    assert "path=99-100" in dup.evidence
    assert "occurrences=2" in dup.evidence
    assert "logistics.railway_route" in by_code
    assert "unknown province 99" in by_code["logistics.railway_route"][0].evidence


def test_duplicate_skips_malformed_and_non_positive():
    tile, prov = _land_2x3()
    rail = _FakeManager([
        RailwayEntry(level=1, province_ids=[0, 1]),
        RailwayEntry(level=1, province_ids=[0, 1]),
        RailwayEntry(level=1, province_ids="12"),
        RailwayEntry(level=1, province_ids="12"),
    ])
    findings = validate_logistics_references(prov, tile, railway_mgr=rail)
    assert "logistics.duplicate_route" not in _by_code(findings)
    assert "logistics.railway_route" in _by_code(findings)


def test_mixed_surface_blocks_railway_but_not_port_water():
    tile = np.array([[TILE_LAND, TILE_SEA, TILE_LAND]], dtype=np.uint8)
    prov = np.array([[1, 1, 2]], dtype=np.int32)
    rail = _FakeManager([RailwayEntry(level=1, province_ids=[1, 2])])
    sup = _FakeManager([SupplyNode(province_id=1, level=1)])
    findings = validate_logistics_references(prov, tile, railway_mgr=rail, supply_mgr=sup)
    by_code = _by_code(findings)
    assert "logistics.railway_route" in by_code
    assert "surface=mixed" in by_code["logistics.railway_route"][0].evidence
    assert "logistics.port" not in by_code


def test_invalid_level_supply_excluded_from_graph():
    tile, prov = _land_2x3()
    rail = RailwayManager()
    rail.add(1, [1, 2])
    sup = _FakeManager([
        SupplyNode(province_id=1, level=1),
        SupplyNode(province_id=3, level=0),
    ])
    findings = validate_logistics_references(prov, tile, railway_mgr=rail, supply_mgr=sup)
    by_code = _by_code(findings)
    assert "logistics.supply_node" in by_code
    assert "illegal level 0" in by_code["logistics.supply_node"][0].evidence
    assert "logistics.graph" not in by_code
