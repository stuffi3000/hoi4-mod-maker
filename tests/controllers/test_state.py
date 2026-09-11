"""StateController unit tests."""
import pytest
import numpy as np

from model.project import Project
from model.events import EventBus
from commands.history import CommandHistory
from controllers.state import StateController


@pytest.fixture
def state_setup():
    """Create Project + CommandHistory + StateController and initialize the minimap."""
    bus = EventBus()
    project = Project(event_bus=bus)
    history = CommandHistory(event_bus=bus)

    # Create a 4x4 minimap with 2 provinces
    project.map_data.province_map = np.array([
        [1, 1, 2, 2],
        [1, 1, 2, 2],
        [1, 1, 2, 2],
        [1, 1, 2, 2],
    ], dtype=np.int32)
    project.map_data.tile_map = np.ones((4, 4), dtype=np.uint8)

    # Create a State (create_state accepts a list of provinces)
    state = project.state_mgr.create_state([1])
    state.name = "TestState"

    ctrl = StateController(project, history)
    return ctrl, project, history


def test_on_province_clicked_assigns(state_setup):
    ctrl, project, _ = state_setup
    ctrl.selected_state_id = 1
    ctrl.assign_mode = True

    ctrl.on_province_clicked(2)

    # Province 2 should be assigned to State 1
    assert project.state_mgr.get_state_of_province(2) == 1


def test_on_province_clicked_no_state_selected(state_setup):
    ctrl, project, _ = state_setup
    ctrl.selected_state_id = 0

    ctrl.on_province_clicked(2)

    # Province 2 should not be allocated
    assert project.state_mgr.get_state_of_province(2) == 0


def test_select_state_changes_id(state_setup):
    ctrl, _, _ = state_setup
    assert ctrl.selected_state_id == 0
    ctrl.select_state(1)
    assert ctrl.selected_state_id == 1


def test_change_property_name(state_setup):
    ctrl, project, _ = state_setup
    ctrl.change_property(1, "name", "NewName")
    state = project.state_mgr.get_state(1)
    assert state.name == "NewName"


def test_set_vp(state_setup):
    ctrl, project, _ = state_setup
    ctrl.set_vp(1, 10)
    state = project.state_mgr.get_state(1)
    assert state.victory_points.get(1) == 10


def test_set_vp_with_name(state_setup):
    ctrl, project, _ = state_setup
    ctrl.set_vp(1, 10, "Stuttgart")
    state = project.state_mgr.get_state(1)
    assert state.victory_points.get(1) == 10
    assert state.vp_names.get(1) == "Stuttgart"
    # Empty name = clear old name
    ctrl.set_vp(1, 10, "")
    assert state.vp_names.get(1) == ""


def test_set_vp_zero_removes(state_setup):
    ctrl, project, _ = state_setup
    ctrl.set_vp(1, 5)
    ctrl.set_vp(1, 0)
    state = project.state_mgr.get_state(1)
    assert 1 not in state.victory_points
