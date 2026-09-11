"""CountryController unit test - info/dispatch dual mode."""
import pytest
import numpy as np

from model.project import Project
from model.events import EventBus
from commands.history import CommandHistory
from controllers.country import CountryController


@pytest.fixture
def country_setup():
    """Project + CountryController: 2 provinces and 2 states, 1 country and 1 state."""
    bus = EventBus()
    project = Project(event_bus=bus)
    history = CommandHistory(event_bus=bus)

    project.map_data.province_map = np.array([
        [1, 1, 2, 2],
        [1, 1, 2, 2],
        [1, 1, 2, 2],
        [1, 1, 2, 2],
    ], dtype=np.int32)
    project.map_data.tile_map = np.ones((4, 4), dtype=np.uint8)

    project.state_mgr.create_state([1])   # State 1 ← Province 1
    project.state_mgr.create_state([2])   # State 2 ← Province 2

    ctrl = CountryController(project, history)
    ctrl.create_country("AAA", "Alpha", (10, 20, 30))
    project.country_mgr.assign_state(1, "AAA")
    return ctrl, project, history


def test_default_is_info_mode(country_setup):
    ctrl, _, _ = country_setup
    assert ctrl.assign_mode is False


def test_info_mode_click_selects_owner_not_reassign(country_setup):
    ctrl, project, _ = country_setup
    ctrl.create_country("BBB", "Beta", (40, 50, 60))
    project.country_mgr.assign_state(2, "BBB")
    ctrl.selected_country_tag = "AAA"

    ctrl.on_province_clicked(2)   # Information mode point BBB location

    # Only toggle selection, do not change ownership
    assert ctrl.selected_country_tag == "BBB"
    assert project.country_mgr.get_owner_of_state(2) == "BBB"


def test_assign_mode_click_assigns(country_setup):
    ctrl, project, _ = country_setup
    ctrl.selected_country_tag = "AAA"
    ctrl.set_assign_mode(True)

    ctrl.on_province_clicked(2)

    assert project.country_mgr.get_owner_of_state(2) == "AAA"


def test_assign_undo_returns_to_previous_owner(country_setup):
    ctrl, project, history = country_setup
    ctrl.create_country("BBB", "Beta", (40, 50, 60))
    project.country_mgr.assign_state(2, "BBB")
    ctrl.selected_country_tag = "AAA"
    ctrl.set_assign_mode(True)

    ctrl.on_province_clicked(2)   # BBB State 2 → AAA
    assert project.country_mgr.get_owner_of_state(2) == "AAA"

    history.undo()                # Withdraw → Return to BBB
    assert project.country_mgr.get_owner_of_state(2) == "BBB"


def test_assign_mode_without_selection_does_nothing(country_setup):
    ctrl, project, _ = country_setup
    ctrl.selected_country_tag = ""
    ctrl.set_assign_mode(True)

    ctrl.on_province_clicked(2)

    assert project.country_mgr.get_owner_of_state(2) == ""


def test_deactivate_resets_assign_mode(country_setup):
    ctrl, _, _ = country_setup
    ctrl.set_assign_mode(True)
    ctrl.deactivate()
    assert ctrl.assign_mode is False
