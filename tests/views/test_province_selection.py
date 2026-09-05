"""Province editor multi-selection and context-delete routing tests."""

from types import SimpleNamespace

from views.canvas.widget import MapCanvas
from views.context_menu import ProvinceContextMenu


def test_ctrl_style_additive_selection_and_regular_reset():
    canvas = SimpleNamespace(
        _selected_province_id=0,
        _selected_province_ids=set(),
        _selected_province_tile=0,
    )

    assert MapCanvas.select_province(canvas, 2, 1) == {2}
    assert MapCanvas.select_province(canvas, 5, 1, additive=True) == {2, 5}
    assert MapCanvas.select_province(canvas, 7, 1) == {7}
    assert MapCanvas.select_province(canvas, 0) == set()


def test_context_delete_forwards_complete_selection():
    deleted = []
    menu = ProvinceContextMenu(
        project=SimpleNamespace(),
        controllers={},
        canvas=SimpleNamespace(),
        delete_provinces=lambda pids: deleted.append(pids),
    )
    delete_action = object()

    menu._handle_action(
        delete_action,
        pid=5,
        terrain_actions={},
        vp_action=None,
        capital_action=None,
        copy_action=object(),
        delete_action=delete_action,
        selected_pids={2, 5, 7},
    )

    assert deleted == [{2, 5, 7}]
