"""Tests for undoable single- and multi-province deletion."""

from types import SimpleNamespace

import numpy as np

from commands.province.delete import DeleteProvincesCommand
from domain.managers.adjacency import AdjacencyEntry, AdjacencyManager
from domain.managers.adjacency_rule import AdjacencyRule, AdjacencyRuleManager
from domain.managers.continent import ContinentManager
from domain.managers.country import CountryManager
from domain.managers.railway import RailwayManager
from domain.managers.state import StateManager
from domain.managers.strategic_region import StrategicRegionManager
from domain.managers.supply_node import SupplyNodeManager


def _make_project():
    province_map = np.array(
        [
            [1, 1, 2, 2, 3, 3],
            [1, 1, 2, 2, 3, 3],
        ],
        dtype=np.int32,
    )
    map_data = SimpleNamespace(
        province_map=province_map,
        provincial_terrain={1: "plains", 2: "forest", 3: "hills"},
    )

    state_mgr = StateManager()
    state = state_mgr.create_state([1, 2, 3])
    state.victory_points = {2: 5, 3: 10}
    state.vp_names = {2: "Two", 3: "Three"}
    state.vp_names_en = {2: "Two EN", 3: "Three EN"}
    state.province_buildings = {2: {"bunker": 1}, 3: {"naval_base": 2}}

    country_mgr = CountryManager()
    country_mgr.create_country("T01", "Test", (1, 2, 3))
    country_mgr.assign_state(state.id, "T01")
    country_mgr.set_capital("T01", 2)

    continent_mgr = ContinentManager()
    continent_mgr.assign_provinces([1, 2, 3], 0)

    strategic_region_mgr = StrategicRegionManager()
    region = strategic_region_mgr.create_region("Test Region")
    region.province_ids = [1, 2, 3]

    adjacency_mgr = AdjacencyManager()
    adjacency_mgr.add(AdjacencyEntry(1, 2))
    adjacency_mgr.add(AdjacencyEntry(1, 3))

    railway_mgr = RailwayManager()
    railway_mgr.add(2, [1, 2, 3])

    supply_mgr = SupplyNodeManager()
    supply_mgr.add(2)

    adjacency_rule_mgr = AdjacencyRuleManager()
    adjacency_rule_mgr.add(
        AdjacencyRule("TEST_RULE", required_provinces=[1, 2], icon_province=2)
    )

    return SimpleNamespace(
        map_data=map_data,
        state_mgr=state_mgr,
        country_mgr=country_mgr,
        continent_mgr=continent_mgr,
        adjacency_mgr=adjacency_mgr,
        railway_mgr=railway_mgr,
        supply_mgr=supply_mgr,
        adjacency_rule_mgr=adjacency_rule_mgr,
        strategic_region_mgr=strategic_region_mgr,
    )


def test_delete_multiple_provinces_cleans_references():
    project = _make_project()

    command = DeleteProvincesCommand(project, {2, 3})
    command.execute()

    assert set(np.unique(project.map_data.province_map)) == {0, 1}
    state = project.state_mgr.get_state(1)
    assert state.provinces == [1]
    assert state.victory_points == {}
    assert state.vp_names == {}
    assert state.vp_names_en == {}
    assert state.province_buildings == {}
    assert project.country_mgr.get_country("T01").capital == 1
    assert project.strategic_region_mgr.get(1).province_ids == [1]
    assert project.continent_mgr._province_continent == {1: 0}
    assert project.adjacency_mgr.count() == 0
    assert project.railway_mgr.count() == 0
    assert project.supply_mgr.count() == 0
    assert project.adjacency_rule_mgr.count() == 0
    assert project.map_data.provincial_terrain == {1: "plains"}


def test_undo_and_redo_restore_everything():
    project = _make_project()
    original_map = project.map_data.province_map.copy()

    command = DeleteProvincesCommand(project, {2, 3})
    command.execute()
    command.undo()

    assert np.array_equal(project.map_data.province_map, original_map)
    state = project.state_mgr.get_state(1)
    assert state.provinces == [1, 2, 3]
    assert state.victory_points == {2: 5, 3: 10}
    assert project.country_mgr.get_country("T01").capital == 2
    assert project.strategic_region_mgr.get(1).province_ids == [1, 2, 3]
    assert project.continent_mgr._province_continent == {1: 0, 2: 0, 3: 0}
    assert project.adjacency_mgr.count() == 2
    assert project.railway_mgr.count() == 1
    assert project.supply_mgr.contains(2)
    assert project.adjacency_rule_mgr.count() == 1
    assert project.map_data.provincial_terrain[2] == "forest"

    command.execute()
    assert set(np.unique(project.map_data.province_map)) == {0, 1}
    assert project.country_mgr.get_country("T01").capital == 1


def test_deleting_only_owned_province_unsets_capital():
    project = _make_project()
    project.state_mgr.get_state(1).provinces = [2]
    project.state_mgr._province_to_state = {2: 1}

    DeleteProvincesCommand(project, {2}).execute()

    assert project.country_mgr.get_country("T01").capital == 0
