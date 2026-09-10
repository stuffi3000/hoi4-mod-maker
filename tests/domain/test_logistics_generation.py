from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from commands.history import CommandHistory
from commands.map.generate_logistics import GenerateLogisticsCommand
from data.constants import TILE_LAND, TILE_SEA
from domain.generators.logistics import generate_logistics, reference_route_mask
from domain.managers.adjacency import AdjacencyManager, AdjacencyEntry
from domain.managers.country import CountryManager
from domain.managers.railway import RailwayManager
from domain.managers.state import StateManager
from domain.managers.supply_node import SupplyNodeManager
from model.events import EventBus
from export.writers.map.railways import write_railways_txt


def project_fixture():
    project = SimpleNamespace(
        map_data=SimpleNamespace(province_map=np.array([[1, 2, 3, 4, 5, 6]]),
                                 tile_map=np.array([[TILE_LAND] * 4 + [TILE_SEA, TILE_LAND]])),
        state_mgr=StateManager(), country_mgr=CountryManager(),
        railway_mgr=RailwayManager(), supply_mgr=SupplyNodeManager(),
        adjacency_mgr=AdjacencyManager(), event_bus=EventBus(), mark_dirty=lambda: None,
    )
    state = project.state_mgr.create_state([1, 2, 3, 4, 5, 6])
    state.victory_points = {1: 10, 4: 5, 6: 1}
    return project


def test_map_routes_connect_targets_without_crossing_sea():
    proposal = generate_logistics(project_fixture())
    assert proposal.edges == [(1, 2), (2, 3), (3, 4)]
    assert proposal.hubs == [1, 4, 6]


def test_stateless_and_impassable_provinces_break_routes():
    project = project_fixture()
    project.adjacency_mgr.add(AdjacencyEntry(2, 3, "impassable"))
    assert (2, 3) not in generate_logistics(project).edges
    project.state_mgr.states[1].provinces.remove(2)
    assert all(2 not in edge for edge in generate_logistics(project).edges)


def test_reference_limits_routes_to_matching_provinces(tmp_path):
    pixels = np.array([[[255, 0, 0, 255], [250, 5, 5, 255], [255, 0, 0, 0],
                        [0, 0, 0, 255], [255, 0, 0, 255], [0, 0, 0, 255]]], dtype=np.uint8)
    path = tmp_path / "reference.png"
    Image.fromarray(pixels).save(path)
    mask = reference_route_mask(path, (1, 6), tolerance=10)
    assert mask.tolist() == [[True, True, False, False, True, False]]
    proposal = generate_logistics(project_fixture(), mask)
    assert proposal.edges == [(1, 2)]
    assert proposal.hubs == [1, 2]


def test_empty_reference_and_missing_states_are_actionable():
    project = project_fixture()
    with pytest.raises(ValueError, match="reference route color"):
        generate_logistics(project, np.zeros((1, 6), dtype=bool))
    project.state_mgr.clear()
    with pytest.raises(ValueError, match="Assign land provinces"):
        generate_logistics(project)


def test_generation_preserves_existing_and_undo_redo():
    project = project_fixture()
    project.railway_mgr.add(5, [1, 2])
    project.supply_mgr.add(1, 2)
    before = project.railway_mgr.to_dict(), project.supply_mgr.to_dict()
    proposal = generate_logistics(project)
    history = CommandHistory()
    history.execute(GenerateLogisticsCommand(project, proposal, level=3))
    after = project.railway_mgr.to_dict(), project.supply_mgr.to_dict()
    assert project.railway_mgr.count() == 3
    assert project.railway_mgr.get_all()[0].level == 5
    assert project.supply_mgr.get_all()[0].level == 2
    history.undo()
    assert (project.railway_mgr.to_dict(), project.supply_mgr.to_dict()) == before
    history.redo()
    assert (project.railway_mgr.to_dict(), project.supply_mgr.to_dict()) == after
    history.execute(GenerateLogisticsCommand(project, proposal, level=1, supply=False, replace=True))
    assert all(e.level == 1 for e in project.railway_mgr.get_all())
    assert project.supply_mgr.to_dict() == after[1]


def test_generation_does_not_duplicate_edge_inside_existing_path():
    project = project_fixture()
    project.railway_mgr.add(5, [1, 2, 3])
    proposal = generate_logistics(project)
    GenerateLogisticsCommand(project, proposal).execute()
    assert not any(entry.province_ids == [1, 2]
                   for entry in project.railway_mgr.get_all())


def test_export_preserves_generated_tree_without_adding_cross_links(tmp_path):
    project = project_fixture()
    project.map_data.province_map = np.array([[1, 2], [3, 4]])
    project.map_data.tile_map = np.full((2, 2), TILE_LAND)
    project.state_mgr.states[1].provinces = [1, 2, 3, 4]
    project.state_mgr.states[1].victory_points = {1: 10, 3: 5, 4: 5}
    proposal = generate_logistics(project)
    GenerateLogisticsCommand(project, proposal).execute()
    write_railways_txt(str(tmp_path), project.railway_mgr, project.map_data.province_map)
    lines = (tmp_path / "map" / "railways.txt").read_text().splitlines()
    exported = {tuple(sorted(map(int, line.split()[2:]))) for line in lines}
    assert exported == set(proposal.edges)


def test_export_still_connects_neighboring_brush_placeholders(tmp_path):
    project = project_fixture()
    project.railway_mgr.set_province_level(1, 4)
    project.railway_mgr.set_province_level(2, 3)
    project.railway_mgr.set_province_level(4, 2)
    write_railways_txt(str(tmp_path), project.railway_mgr, project.map_data.province_map)
    lines = (tmp_path / "map" / "railways.txt").read_text().splitlines()
    assert lines == ["3 2 1 2"]
