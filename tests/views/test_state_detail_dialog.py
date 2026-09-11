"""State details dialog tests for editable victory-point values."""

import pytest
from PyQt5.QtWidgets import QApplication

from domain.managers.state import StateData
from features.map.state.detail_dialog import StateDetailDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_state_detail_vp_values_are_editable(qapp, qtbot):
    state = StateData(id=7, name="Test State")
    state.victory_points = {101: 5, 102: 10}
    state.vp_names = {101: "Alpha", 102: "Bravo"}
    state.vp_names_en = {101: "Alpha EN", 102: "Bravo EN"}

    dialog = StateDetailDialog(state, [], parent=None)
    qtbot.addWidget(dialog)
    dialog._vp_value_spins[101].setValue(25)
    dialog._vp_value_spins[102].setValue(0)

    dialog._on_accept()

    assert state.victory_points == {101: 25}
    assert state.vp_names == {101: "Alpha"}
    assert state.vp_names_en == {101: "Alpha EN"}
