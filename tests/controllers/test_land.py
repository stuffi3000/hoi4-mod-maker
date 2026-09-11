"""LandController unit tests."""
import pytest

from model.project import Project
from model.events import EventBus
from commands.history import CommandHistory
from controllers.land import LandController


@pytest.fixture
def land_setup():
    """Create Project + CommandHistory + LandController."""
    bus = EventBus()
    project = Project(event_bus=bus)
    history = CommandHistory(event_bus=bus)
    ctrl = LandController(project, history)
    return ctrl, project, history


def test_activate_sets_defaults(land_setup):
    ctrl, _, _ = land_setup
    ctrl.current_tool = "fill"
    ctrl.brush_size = 20
    ctrl.activate()
    assert ctrl.current_tool == "brush"
    assert ctrl._is_painting is False


def test_stores_tool_and_tile_type(land_setup):
    ctrl, _, _ = land_setup
    ctrl.current_tool = "eraser"
    assert ctrl.current_tool == "eraser"
    ctrl.current_tile_type = 2
    assert ctrl.current_tile_type == 2
    ctrl.brush_size = 10
    assert ctrl.brush_size == 10


def test_on_press_fill_returns_true(land_setup):
    ctrl, project, _ = land_setup
    # Map data is required
    import numpy as np
    project.map_data.tile_map = np.zeros((16, 16), dtype=np.uint8)
    ctrl.current_tool = "fill"
    ctrl.current_tile_type = 1
    handled = ctrl.on_press(5, 5, 0, "left", set())
    assert handled is True


def test_on_press_right_button_ignored(land_setup):
    ctrl, _, _ = land_setup
    ctrl.current_tool = "brush"
    handled = ctrl.on_press(5, 5, 0, "right", set())
    assert handled is False
