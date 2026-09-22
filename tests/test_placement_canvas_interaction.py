"""Focused tests for placement marker selection and drag intent."""

from copy import deepcopy

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def placement_canvas(qapp, qtbot):
    from views.canvas.widget import MapCanvas

    canvas = MapCanvas()
    qtbot.addWidget(canvas)
    canvas._display_buffer = np.zeros((40, 60, 4), dtype=np.uint8)
    canvas._scene.setSceneRect(0, 0, 60, 40)
    records = [
        {"province_id": 1, "slot": 0, "x": 5.5, "y": 5.5},
        {"province_id": 2, "sea_province": 9, "x": 15.5, "y": 5.5},
        {"id": 7, "province_id": 3, "building_type": "arms_factory", "x": 25.5, "y": 5.5},
        {"id": 11, "region_id": 4, "x": 35.5, "y": 5.5},
    ]
    vp_points = [(20, 45.5, 30.5)]
    findings = [{"code": "placement.collision", "coordinates": [(2.5, 30.5)]}]
    canvas.set_placement_overlay_data(records, vp_points=vp_points, findings=findings)
    canvas.set_placement_overlay_visible(True)
    canvas._display_mode = "strategic_region"
    yield canvas, records
    canvas.set_placement_overlay_visible(False)


def test_hit_testing_returns_typed_selectable_keys_and_skips_diagnostics(placement_canvas):
    canvas, _records = placement_canvas

    assert canvas.placement_marker_at(5.5, 5.5)[:2] == ("slot", (1, 0))
    assert canvas.placement_marker_at(15.5, 5.5)[:2] == ("port", 2)
    assert canvas.placement_marker_at(25.5, 5.5)[:2] == ("building", 7)
    assert canvas.placement_marker_at(35.5, 5.5)[:2] == ("weather", 11)
    assert canvas.placement_marker_at(45.5, 30.5)[:2] == ("vp", 20)
    assert canvas.placement_marker_at(2.5, 30.5) is None
    assert canvas.placement_marker_at(0.0, 39.0) is None


def test_selection_and_empty_click_emit_typed_signals(placement_canvas):
    canvas, _records = placement_canvas
    selections = []
    canvas.placement_selection_changed.connect(
        lambda kind, key: selections.append((kind, key))
    )

    assert canvas._begin_placement_drag(5.5, 5.5) is True
    assert canvas._placement_selected == ("slot", (1, 0))
    assert canvas._placement_selection_item.isVisible()

    canvas._begin_placement_drag(0.0, 39.0)
    assert selections == [("slot", (1, 0)), ("", None)]
    assert not canvas._placement_selection_item.isVisible()


def test_drag_emits_one_position_request_without_mutating_records(placement_canvas):
    canvas, records = placement_canvas
    before = deepcopy(records)
    positions = []
    canvas.placement_position_change_requested.connect(
        lambda kind, key, x, y: positions.append((kind, key, x, y))
    )

    canvas._begin_placement_drag(15.5, 5.5)
    canvas._update_placement_drag(18.25, 7.75)
    assert canvas._placement_selection_item.pos().x() == pytest.approx(18.25)
    assert canvas._placement_selection_item.pos().y() == pytest.approx(7.75)
    canvas._finish_placement_drag()

    assert positions == [("port", 2, 18.25, 7.75)]
    assert records == before
    assert canvas._placement_selected == ("port", 2)
    assert canvas._placement_selection_item.isVisible()

    canvas._begin_placement_drag(18.25, 7.75)
    canvas._finish_placement_drag()
    assert positions == [("port", 2, 18.25, 7.75)]


def test_drag_clamps_to_map_bounds_and_selection_layer_order(placement_canvas):
    canvas, _records = placement_canvas
    positions = []
    canvas.placement_position_change_requested.connect(
        lambda kind, key, x, y: positions.append((kind, key, x, y))
    )

    canvas._begin_placement_drag(5.5, 5.5)
    canvas._update_placement_drag(500.0, -40.0)
    canvas._finish_placement_drag()

    assert positions == [("slot", (1, 0), 59.0, 0.0)]
    assert canvas._placement_selection_item.zValue() > canvas._placement_overlay_item.zValue()
    assert canvas._placement_selection_item.zValue() < canvas._transform_border.zValue()


def test_disabled_overlay_clears_hit_testing_and_selection(placement_canvas):
    canvas, _records = placement_canvas
    canvas._begin_placement_drag(5.5, 5.5)
    canvas.set_placement_overlay_visible(False)

    assert canvas.placement_marker_at(5.5, 5.5) is None
    assert canvas._placement_selected is None
    assert not canvas._placement_selection_item.isVisible()
    assert not canvas._placement_overlay_item.isVisible()


def test_existing_vp_overlay_can_coexist(placement_canvas):
    canvas, _records = placement_canvas
    canvas._vp_data = {1: 5}
    canvas._vp_cache_dirty = True
    canvas._display_mode = "province"
    canvas._update_vp_visibility()

    assert canvas._vp_overlay_item.isVisible()
    assert canvas._placement_overlay_item.isVisible()
    assert canvas.placement_marker_at(45.5, 30.5)[:2] == ("vp", 20)


def test_selection_filter_isolates_overlapping_marker_types(placement_canvas):
    canvas, _records = placement_canvas
    point = (12.5, 12.5)
    canvas.set_placement_overlay_data(
        [
            {"province_id": 1, "slot": 0, "x": point[0], "y": point[1]},
            {"province_id": 2, "sea_province": 9, "x": point[0], "y": point[1]},
            {"id": 7, "province_id": 3, "building_type": "arms_factory", "x": point[0], "y": point[1]},
        ],
        vp_points=[(20, point[0], point[1])],
    )

    canvas.set_placement_selection_filter("building")
    assert canvas.placement_marker_at(*point)[:2] in {("slot", (1, 0)), ("building", 7)}
    canvas.set_placement_selection_filter("port")
    assert canvas.placement_marker_at(*point)[:2] == ("port", 2)
    canvas.set_placement_selection_filter("vp")
    assert canvas.placement_marker_at(*point)[:2] == ("vp", 20)


def test_victory_point_selection_does_not_start_a_drag(placement_canvas):
    canvas, _records = placement_canvas
    assert canvas._begin_placement_drag(45.5, 30.5) is True
    assert canvas._placement_selected == ("vp", 20)
    assert canvas._placement_drag_state is None
    assert canvas._finish_placement_drag() is True


def test_input_router_emits_drag_intent_only_on_release(placement_canvas):
    canvas, _records = placement_canvas
    positions = []
    canvas.placement_position_change_requested.connect(
        lambda kind, key, x, y: positions.append((kind, key, x, y))
    )
    scene_points = [(15.5, 5.5), (18.25, 7.75)]
    canvas._scene_pos_float = lambda _event: scene_points.pop(0)

    def mouse_event(event_type):
        return QMouseEvent(
            event_type,
            QPointF(0.0, 0.0),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )

    canvas.mousePressEvent(mouse_event(QEvent.MouseButtonPress))
    assert positions == []
    canvas.mouseMoveEvent(mouse_event(QEvent.MouseMove))
    assert positions == []
    canvas.mouseReleaseEvent(mouse_event(QEvent.MouseButtonRelease))
    assert positions == [("port", 2, 18.25, 7.75)]
