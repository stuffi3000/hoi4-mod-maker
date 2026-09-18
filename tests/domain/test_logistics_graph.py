"""Focused M4.4 logistics graph tests (synthetic, no game install)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.logistics_graph import (
    analyze_logistics_graph,
    build_logistics_graph,
    component_id_for,
)
from domain.managers.railway import RailwayManager
from domain.managers.supply_node import SupplyNodeManager

pytestmark = pytest.mark.unit


def _fixture_managers() -> tuple[RailwayManager, SupplyNodeManager]:
    """Two railway components plus one supply-only province.

    Routes cover a reverse duplicate pair and a consecutive self-loop that
    also extends the first component with a fourth province.
    """
    rail = RailwayManager()
    rail.add(2, [1, 2, 3])
    rail.add(1, [3, 2, 1])
    rail.add(3, [2, 2, 4])
    rail.add(1, [10, 11])
    supply = SupplyNodeManager()
    supply.add(1)
    supply.add(4)
    supply.add(11)
    supply.add(99)
    return rail, supply


def _reversed_managers() -> tuple[RailwayManager, SupplyNodeManager]:
    """Same logical content as the fixture in reversed insertion order."""
    rail = RailwayManager()
    rail.add(1, [10, 11])
    rail.add(3, [2, 2, 4])
    rail.add(1, [3, 2, 1])
    rail.add(2, [1, 2, 3])
    supply = SupplyNodeManager()
    supply.add(99)
    supply.add(11)
    supply.add(4)
    supply.add(1)
    return rail, supply


def _duck_managers() -> tuple[SimpleNamespace, SimpleNamespace]:
    """Attribute and mapping style fakes mirroring the fixture content."""
    rail_like = SimpleNamespace(get_all=lambda: [
        SimpleNamespace(level=2, province_ids=[1, 2, 3]),
        SimpleNamespace(level=1, province_ids=[3, 2, 1]),
        {"level": 3, "province_ids": [2, 2, 4]},
        SimpleNamespace(level=1, province_ids=[10, 11]),
    ])
    supply_like = SimpleNamespace(get_all=lambda: [
        {"province_id": 1, "level": 1},
        SimpleNamespace(province_id=4, level=1),
        SimpleNamespace(province_id=11, level=1),
        SimpleNamespace(province_id=99, level=1),
    ])
    return rail_like, supply_like


def _by_provinces(graph) -> dict[tuple[int, ...], object]:
    return {component.provinces: component for component in graph.components}


def test_synthetic_components_supply_selfloop_duplicate():
    """Two railway components, supply-only node, self-loop, reverse duplicate."""
    rail, supply = _fixture_managers()
    graph = analyze_logistics_graph(rail, supply)

    assert graph.vertices == (1, 2, 3, 4, 10, 11, 99)
    assert graph.railway_provinces == (1, 2, 3, 4, 10, 11)
    assert graph.supply_provinces == (1, 4, 11, 99)
    assert graph.supply_on_rail == (1, 4, 11)
    assert graph.supply_off_rail == (99,)
    assert graph.edge_pairs == ((1, 2), (2, 3), (2, 4), (10, 11))
    assert graph.route_count == 4
    assert graph.usable_route_count == 4

    assert graph.component_count == 3
    lookup = _by_provinces(graph)
    assert set(lookup) == {(1, 2, 3, 4), (10, 11), (99,)}
    first = lookup[(1, 2, 3, 4)]
    assert first.railway_provinces == (1, 2, 3, 4)
    assert first.supply_provinces == (1, 4)
    assert first.supply_only_provinces == ()
    assert first.edges == ((1, 2), (2, 3), (2, 4))
    assert first.route_indices == (0, 1, 2)
    assert first.levels == (2, 1, 3)
    lone = lookup[(99,)]
    assert lone.railway_provinces == ()
    assert lone.supply_provinces == (99,)
    assert lone.supply_only_provinces == (99,)
    assert lone.edges == ()

    assert len(graph.duplicates) == 1
    duplicate = graph.duplicates[0]
    assert duplicate.path_key == (1, 2, 3)
    assert duplicate.route_indices == (0, 1)
    assert duplicate.levels == (2, 1)
    assert duplicate.occurrences == 2

    kinds = {(loop.province_id, loop.kind) for loop in graph.self_loops}
    assert (2, "consecutive") in kinds
    consecutive = [loop for loop in graph.self_loops if loop.kind == "consecutive"]
    assert consecutive[0].route_index == 2
    assert consecutive[0].level == 3

    assert len(graph.candidates) == 3
    assert build_logistics_graph(rail, supply) == graph


def test_reversed_insertion_order_keeps_topology_and_identities():
    """Determinism under reversed manager order for order-free content."""
    forward = analyze_logistics_graph(*_fixture_managers())
    reversed_graph = analyze_logistics_graph(*_reversed_managers())

    assert reversed_graph.vertices == forward.vertices
    assert reversed_graph.edge_pairs == forward.edge_pairs
    assert reversed_graph.supply_on_rail == forward.supply_on_rail
    assert reversed_graph.supply_off_rail == forward.supply_off_rail
    assert sorted(reversed_graph.component_ids) == sorted(forward.component_ids)
    assert [dup.path_key for dup in reversed_graph.duplicates] == [dup.path_key for dup in forward.duplicates]
    assert [dup.occurrences for dup in reversed_graph.duplicates] == [dup.occurrences for dup in forward.duplicates]
    forward_loops = sorted((loop.province_id, loop.kind) for loop in forward.self_loops)
    reversed_loops = sorted((loop.province_id, loop.kind) for loop in reversed_graph.self_loops)
    assert reversed_loops == forward_loops
    forward_pairs = [(item.from_province, item.to_province, item.distance) for item in forward.candidates]
    reversed_pairs = [(item.from_province, item.to_province, item.distance) for item in reversed_graph.candidates]
    assert reversed_pairs == forward_pairs
def test_component_identities_stable_and_candidates_ordered():
    """Stable identities plus deterministic nearest-candidate ordering."""
    rail, supply = _fixture_managers()
    first = build_logistics_graph(rail, supply)
    second = build_logistics_graph(rail, supply)

    assert first.component_ids == second.component_ids
    for component in first.components:
        assert component.component_id == component_id_for(
            component.provinces, component.edges, component.supply_provinces
        )
    assert len({component.component_id for component in first.components}) == 3

    pairs = [(item.from_province, item.to_province, item.distance) for item in first.candidates]
    assert pairs == [(4, 10, 6.0), (11, 99, 88.0), (4, 99, 95.0)]
    keys = [(item.distance, item.from_province, item.to_province) for item in first.candidates]
    assert keys == sorted(keys)
    for item in first.candidates:
        assert item.from_province < item.to_province

    capped = build_logistics_graph(rail, supply, max_candidates=1)
    assert [(item.from_province, item.to_province) for item in capped.candidates] == [(4, 10)]


def test_region_summaries_and_port_convoy_flags():
    """Optional state/continent/region summaries with port and convoy flags."""
    rail, supply = _fixture_managers()
    graph = build_logistics_graph(
        rail,
        supply,
        province_to_state={1: 7, 2: 7, 3: 8, 4: 8, 10: 9, 11: 9, 99: 9},
        province_to_continent={1: 1, 2: 1, 3: 1, 4: 1, 10: 1, 11: 1, 99: 2},
        province_to_strategic_region={1: 21, 2: 21, 3: 21, 4: 22, 10: 23, 11: 23, 99: 24},
        port_provinces={11},
        has_convoy_access=lambda pid: pid == 99,
    )
    lookup = _by_provinces(graph)
    first = lookup[(1, 2, 3, 4)]
    assert first.state_ids == (7, 8)
    assert first.state_counts == ((7, 2), (8, 2))
    assert first.continent_ids == (1,)
    assert first.continent_counts == ((1, 4),)
    assert first.strategic_region_ids == (21, 22)
    assert first.strategic_region_counts == ((21, 3), (22, 1))
    assert first.has_port is False
    assert first.has_convoy is False

    second = lookup[(10, 11)]
    assert second.state_ids == (9,)
    assert second.port_provinces == (11,)
    assert second.has_port is True
    assert second.has_convoy is False

    lone = lookup[(99,)]
    assert lone.strategic_region_ids == (24,)
    assert lone.continent_ids == (2,)
    assert lone.convoy_provinces == (99,)
    assert lone.has_convoy is True
    assert lone.has_port is False

    plain = build_logistics_graph(rail, supply)
    for component in plain.components:
        assert component.state_ids == ()
        assert component.continent_ids == ()
        assert component.strategic_region_ids == ()
        assert component.has_port is False
        assert component.has_convoy is False


def test_duck_typed_managers_match_real_managers():
    """Duck-typed mapping/attribute fakes produce the same logical graph."""
    real = build_logistics_graph(*_fixture_managers())
    duck = build_logistics_graph(*_duck_managers())

    assert duck.vertices == real.vertices
    assert duck.edge_pairs == real.edge_pairs
    assert duck.supply_on_rail == real.supply_on_rail
    assert duck.supply_off_rail == real.supply_off_rail
    assert {component.provinces for component in duck.components} == {
        component.provinces for component in real.components
    }
    assert sorted(duck.component_ids) == sorted(real.component_ids)
    assert [dup.path_key for dup in duck.duplicates] == [dup.path_key for dup in real.duplicates]
    duck_loops = sorted((loop.province_id, loop.kind) for loop in duck.self_loops)
    real_loops = sorted((loop.province_id, loop.kind) for loop in real.self_loops)
    assert duck_loops == real_loops

    assert build_logistics_graph(None, None).vertices == ()
    assert build_logistics_graph(None, None).components == ()


def test_known_provinces_filters_graph_but_keeps_duplicate_evidence():
    """An optional known-province set filters vertices while keeping repeats."""
    rail, supply = _fixture_managers()
    graph = build_logistics_graph(rail, supply, known_provinces={1, 2, 3, 4, 10, 11})

    assert 99 not in graph.vertices
    assert graph.supply_off_rail == ()
    assert graph.component_count == 2
    assert len(graph.duplicates) == 1
    assert graph.duplicates[0].path_key == (1, 2, 3)


def test_inputs_are_not_mutated():
    """Graph analysis leaves railway and supply managers untouched."""
    rail, supply = _fixture_managers()
    rail_snapshot = rail.to_dict()
    rail_ids = [list(entry.province_ids) for entry in rail.get_all()]
    supply_snapshot = supply.to_dict()

    build_logistics_graph(
        rail,
        supply,
        province_to_state={1: 7, 2: 7, 3: 8, 4: 8, 10: 9, 11: 9, 99: 9},
        port_provinces={11},
        has_convoy_access=lambda pid: pid == 99,
        max_candidates=2,
    )
    analyze_logistics_graph(rail, supply)

    assert rail.to_dict() == rail_snapshot
    assert [list(entry.province_ids) for entry in rail.get_all()] == rail_ids
    assert supply.to_dict() == supply_snapshot
