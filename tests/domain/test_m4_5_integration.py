from __future__ import annotations

import numpy as np

from domain.logistics_exceptions import (
    LogisticsExceptionManager,
    evaluate_exception_coverage,
)
from domain.logistics_graph import analyze_logistics_graph
from domain.logistics_graph import component_id_for
from domain.managers.country import CountryManager
from domain.managers.railway import RailwayManager
from domain.managers.state import StateManager
from domain.managers.supply_node import SupplyNodeManager
from domain.project_io import load_project, save_project
from domain.validators.logistics import validate_logistics_references
from features.map.logistics.renderer import build_logistics_component_colors
from services.export_planner import plan_export


def _graph_and_managers():
    railway = RailwayManager()
    railway.add(2, [1, 2])
    supply = SupplyNodeManager()
    supply.add(3)
    province_map = np.array([[1, 2, 3]], dtype=np.int32)
    graph = analyze_logistics_graph(
        railway,
        supply,
        known_provinces={1, 2, 3},
    )
    return province_map, graph, railway, supply


def test_exception_coverage_blocks_freeze_until_cases_have_reasons():
    province_map, graph, railway, supply = _graph_and_managers()
    exceptions = LogisticsExceptionManager()
    coverage = evaluate_exception_coverage(exceptions, graph)
    assert coverage.relevant_keys == ("supply:3",)

    pending = validate_logistics_references(
        province_map,
        railway_mgr=railway,
        supply_mgr=supply,
        logistics_exception_mgr=exceptions,
        lifecycle="frozen",
    )
    assert [finding.code for finding in pending] == [
        "logistics.graph",
        "logistics.exception_coverage",
    ]
    assert pending[-1].severity == "blocker"

    component = graph.components[1]
    exceptions.add_component(component.component_id, "island", "separate island")
    exceptions.add_supply(3, component.component_id, "overseas_convoy", "convoy route")
    accepted = validate_logistics_references(
        province_map,
        railway_mgr=railway,
        supply_mgr=supply,
        logistics_exception_mgr=exceptions,
        lifecycle="frozen",
    )
    assert accepted == []


def test_component_renderer_colors_and_highlights_current_findings():
    province_map, graph, _railway, _supply = _graph_and_managers()
    colors = build_logistics_component_colors(province_map, graph)

    assert colors.shape == (1, 3, 3)
    assert tuple(colors[0, 0]) == tuple(colors[0, 1])
    assert tuple(colors[0, 2]) == (245, 52, 194)
    assert tuple(colors[0, 0]) != (232, 72, 72)


def test_stale_supply_exception_remains_a_visible_renderer_finding():
    province_map, graph, _railway, _supply = _graph_and_managers()
    old_component = component_id_for((9,), (), ())
    exceptions = LogisticsExceptionManager()
    exceptions.add_supply(3, old_component, "future_content", "topology changed")

    coverage = evaluate_exception_coverage(exceptions, graph)
    assert coverage.missing_keys == ()
    assert coverage.stale_keys == ("supply:3",)
    colors = build_logistics_component_colors(
        province_map,
        graph,
        exception_manager=exceptions,
    )
    assert tuple(colors[0, 2]) == (245, 52, 194)


def test_project_io_round_trips_logistics_exceptions(tmp_path):
    _province_map, graph, _railway, _supply = _graph_and_managers()
    exceptions = LogisticsExceptionManager()
    component = graph.components[1]
    exceptions.add_component(component.component_id, "future_content", "later rail content")

    states = StateManager()
    countries = CountryManager()
    path = tmp_path / "exceptions.hoi4proj"
    array = np.array([[1, 2, 3]], dtype=np.int32)
    save_project(
        str(path),
        tile_map=np.ones((1, 3), dtype=np.uint8),
        province_map=array,
        terrain_map=np.zeros((1, 3), dtype=np.uint8),
        height_map=np.ones((1, 3), dtype=np.float32),
        state_mgr=states,
        country_mgr=countries,
        logistics_exception_mgr=exceptions,
    )

    restored = LogisticsExceptionManager()
    load_project(
        str(path),
        StateManager(),
        CountryManager(),
        logistics_exception_mgr=restored,
    )
    assert restored.to_dict() == exceptions.to_dict()


def test_export_plan_uses_requested_freeze_lifecycle_for_exception_gate():
    province_map, _graph, railway, supply = _graph_and_managers()
    exceptions = LogisticsExceptionManager()

    plan = plan_export(
        np.ones((1, 3), dtype=np.uint8),
        province_map,
        np.zeros((1, 3), dtype=np.uint8),
        state_mgr=StateManager(),
        country_mgr=CountryManager(),
        railway_mgr=railway,
        supply_mgr=supply,
        logistics_exception_mgr=exceptions,
        lifecycle="frozen",
    )

    assert any("logistics exception cases require review" in blocker for blocker in plan.blockers)
