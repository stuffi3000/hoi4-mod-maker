"""Terrain controller tests for province-mode visual editing."""

import numpy as np
import pytest

from commands.history import CommandHistory
from controllers.terrain import TerrainController
from data.constants import TILE_LAND
from data.terrain_types import TERRAIN_PALETTE_INDEX
from model.events import EventBus
from model.project import Project


@pytest.fixture
def terrain_setup():
    """Create a small two-province land map for terrain controller tests."""
    bus = EventBus()
    project = Project(event_bus=bus)
    history = CommandHistory(event_bus=bus)
    controller = TerrainController(project, history)

    map_data = project.map_data
    map_data.province_map = np.ones((4, 4), dtype=np.int32)
    map_data.province_map[:, 2:] = 2
    map_data.tile_map = np.full((4, 4), TILE_LAND, dtype=np.uint8)
    map_data.terrain_map = np.full(
        (4, 4), TERRAIN_PALETTE_INDEX["plains"], dtype=np.uint8
    )
    return controller, project, history


def test_province_visual_paint_updates_matching_attribute(terrain_setup):
    """Province-mode visual painting also assigns the matching gameplay type."""
    controller, project, _ = terrain_setup
    map_data = project.map_data
    map_data.provincial_terrain[1] = "urban"
    controller.current_terrain_index = TERRAIN_PALETTE_INDEX["forest"]

    controller.on_province_clicked(1)

    assert np.all(
        map_data.terrain_map[:, :2] == TERRAIN_PALETTE_INDEX["forest"]
    )
    assert map_data.provincial_terrain[1] == "forest"


def test_province_visual_paint_sync_is_undoable(terrain_setup):
    """Undo restores both the visual pixels and the previous attribute."""
    controller, project, history = terrain_setup
    map_data = project.map_data
    map_data.terrain_map[:, :2] = TERRAIN_PALETTE_INDEX["plains"]
    map_data.provincial_terrain[1] = "urban"
    controller.current_terrain_index = TERRAIN_PALETTE_INDEX["forest"]

    controller.on_province_clicked(1)
    assert map_data.provincial_terrain[1] == "forest"

    assert history.undo()
    assert np.all(
        map_data.terrain_map[:, :2] == TERRAIN_PALETTE_INDEX["plains"]
    )
    assert map_data.provincial_terrain[1] == "urban"


def test_province_visual_paint_unknown_palette_leaves_attribute(terrain_setup):
    """A graphical-only palette entry does not invent an attribute type."""
    controller, project, _ = terrain_setup
    map_data = project.map_data
    map_data.provincial_terrain[1] = "plains"
    controller.current_terrain_index = 254

    controller.on_province_clicked(1)

    assert map_data.provincial_terrain[1] == "plains"
    assert np.all(map_data.terrain_map[:, :2] == 254)
