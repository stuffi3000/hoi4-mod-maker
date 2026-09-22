"""Qt behavior tests for the map Find dialog."""

import numpy as np

from domain.managers.state import StateData
from model.project import Project
from services.find_service import FindService
from views.find_dialog import FindDialog


def _service() -> FindService:
    project = Project()
    project.map_data.province_map = np.array([[1, 1, 2, 2]], dtype=np.int32)
    project.state_mgr._states = {
        1: StateData(id=1, name="Northern Coast", provinces=[1]),
    }
    return FindService(project)


def test_suggestions_can_be_used_for_a_second_search(qtbot) -> None:
    located = []
    dialog = FindDialog(_service(), located.append)
    qtbot.addWidget(dialog)

    dialog._search_edit.setText("Northrn Coast")
    dialog._perform_search()

    assert dialog._results_list.count() == 0
    assert dialog._suggestions_list.count() == 1

    dialog._on_suggestion_clicked(dialog._suggestions_list.item(0))

    assert dialog._results_list.count() == 1
    assert located and located[-1].kind == "state"
