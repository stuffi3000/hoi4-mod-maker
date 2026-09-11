"""ProvincialTerrainController unit test - focus on covering sync_from_visual."""
import numpy as np
import pytest

from model.project import Project
from model.events import EventBus
from commands.history import CommandHistory
from controllers.provincial_terrain import ProvincialTerrainController
from data.constants import TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX


@pytest.fixture
def pterrain_setup():
    """Create Project + CommandHistory + ProvincialTerrainController.

    Map: 8x8, province 1 (left half) + province 2 (right half), all land.
    Visual terrain: Province 1 = forest, Province 2 = mountain."""
    bus = EventBus()
    project = Project(event_bus=bus)
    history = CommandHistory(event_bus=bus)
    ctrl = ProvincialTerrainController(project, history)

    md = project.map_data
    md.province_map = np.ones((8, 8), dtype=np.int32)
    md.province_map[:, 4:] = 2
    md.tile_map = np.full((8, 8), TILE_LAND, dtype=np.uint8)
    md.terrain_map = np.full((8, 8), TERRAIN_PALETTE_INDEX["forest"], dtype=np.uint8)
    md.terrain_map[:, 4:] = TERRAIN_PALETTE_INDEX["mountain"]
    return ctrl, project, history


def test_sync_from_visual_overwrites_manual(pterrain_setup):
    """Manually set attributes will also be overridden by visual majority terrain."""
    ctrl, project, _ = pterrain_setup
    md = project.map_data
    md.provincial_terrain[1] = "urban"   # Manual setting, inconsistent with vision (forest)
    md.provincial_terrain[2] = "mountain"  # Already consistent with vision

    ctrl.sync_from_visual()

    assert md.provincial_terrain[1] == "forest"
    assert md.provincial_terrain[2] == "mountain"


def test_sync_from_visual_undoable(pterrain_setup):
    """Synchronize command history, Ctrl+Z can restore manual settings."""
    ctrl, project, history = pterrain_setup
    md = project.map_data
    md.provincial_terrain[1] = "urban"

    ctrl.sync_from_visual()
    assert md.provincial_terrain[1] == "forest"

    history.undo()
    assert md.provincial_terrain[1] == "urban"


def test_sync_from_visual_nochange_no_command(pterrain_setup):
    """No command is generated when the attributes are consistent (the undo stack remains unchanged)."""
    ctrl, project, history = pterrain_setup
    md = project.map_data
    md.provincial_terrain[1] = "forest"
    md.provincial_terrain[2] = "mountain"

    ctrl.sync_from_visual()

    assert history.can_undo is False


def test_sync_from_visual_skips_sea_province(pterrain_setup):
    """Maritime provinces are not written to the attribute dict."""
    ctrl, project, _ = pterrain_setup
    md = project.map_data
    md.tile_map[:, 4:] = TILE_SEA  # Province 2 becomes ocean

    ctrl.sync_from_visual()

    assert md.provincial_terrain.get(1) == "forest"
    assert 2 not in md.provincial_terrain
