"""Focused tests for the read-only placement canvas overlay."""

import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def small_canvas(qapp, qtbot):
    """Real canvas shrunk to a small map size for cheap pixmap assertions."""
    import views.canvas.widget as widget_mod
    import data.constants as constants
    from data.constants import TILE_LAND, TILE_SEA, set_map_size
    old_w, old_h = constants.MAP_WIDTH, constants.MAP_HEIGHT
    set_map_size(widget_mod.MAP_WIDTH, widget_mod.MAP_HEIGHT)
    try:
        canvas = widget_mod.MapCanvas()
        qtbot.addWidget(canvas)
        canvas._display_buffer = np.zeros((32, 48, 4), dtype=np.uint8)
        canvas._province_map = np.zeros((32, 48), dtype=np.int32)
        canvas._province_map[:, :24] = 1
        canvas._province_map[:, 24:] = 2
        canvas._tile_map = np.full((32, 48), TILE_SEA, dtype=np.uint8)
        canvas._tile_map[:, :24] = TILE_LAND
        canvas._scene.setSceneRect(0, 0, 48, 32)
        yield canvas
    finally:
        set_map_size(old_w, old_h)


def _demo_inputs():
    records = [
        {"province_id": 1, "slot": 0, "x": 5.5, "y": 6.5, "provenance": "generated", "review_status": "reviewed"},
        {"province_id": 2, "sea_province": 9, "x": 10.25, "y": 8.75, "provenance": "generated"},
        {"id": 7, "province_id": 2, "building_type": "arms_factory", "x": 15.5, "y": 12.5, "provenance": "authored"},
        {"id": 11, "region_id": 4, "x": 20.5, "y": 18.5},
    ]
    vp_points = [(3, 25.5, 10.5), {"province_id": 4, "x": 30.5, "y": 20.5}]
    findings = [
        {"code": "placement.collision", "coordinates": [[12.5, 14.5]]},
        {"code": "other", "coordinates": [[1.0, 1.0]]},
    ]
    return records, vp_points, findings


def _alpha_count(image):
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 0:
                count += 1
    return count


def _neighborhood_has_paint(image, cx, cy, radius=5):
    x0 = max(0, int(float(cx)) - radius)
    x1 = min(image.width() - 1, int(float(cx)) + radius)
    y0 = max(0, int(float(cy)) - radius)
    y1 = min(image.height() - 1, int(float(cy)) + radius)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if image.pixelColor(x, y).alpha() > 0:
                return True
    return False


def test_hidden_by_default_and_z_order(small_canvas):
    """Overlay starts hidden above VP/context but below interaction layers."""
    canvas = small_canvas
    assert canvas._placement_overlay_item is not None
    assert not canvas._placement_overlay_item.isVisible()
    assert canvas._placement_overlay_item.zValue() > canvas._vp_overlay_item.zValue()
    assert canvas._placement_overlay_item.zValue() > canvas._terrain_context_overlay.zValue()
    assert canvas._placement_overlay_item.zValue() < canvas._lasso_overlay.zValue()
    assert canvas._placement_overlay_item.zValue() < canvas._brush_cursor.zValue()
    assert not canvas._placement_context_item.isVisible()


def test_context_layer_shows_province_borders_and_coastlines(small_canvas):
    canvas = small_canvas
    canvas.set_placement_overlay_visible(True)

    assert canvas._placement_context_item.isVisible()
    pixmap = canvas._placement_context_item.pixmap()
    assert pixmap.width() == canvas.map_w
    assert pixmap.height() == canvas.map_h
    image = pixmap.toImage()
    assert _alpha_count(image) > 0

    canvas.set_placement_overlay_visible(False)
    assert not canvas._placement_context_item.isVisible()


def test_data_does_not_auto_show_and_disable_clears(small_canvas):
    """Providing data re-renders without auto-showing; disabling hides/clears."""
    canvas = small_canvas
    records, vp_points, findings = _demo_inputs()
    canvas.set_placement_overlay_data(records, vp_points=vp_points, findings=findings)
    assert not canvas._placement_overlay_item.isVisible()
    canvas.set_placement_overlay_visible(True)
    assert canvas._placement_overlay_item.isVisible()
    canvas.set_placement_overlay_visible(False)
    assert not canvas._placement_overlay_item.isVisible()
    assert canvas._placement_overlay_item.pixmap().isNull()


def test_enabled_renders_markers_with_dimensions(small_canvas):
    """Model-driven markers render into a map-sized transparent pixmap."""
    from features.map.placement.overlay import build_placement_overlay_model
    canvas = small_canvas
    records, vp_points, findings = _demo_inputs()
    canvas.set_placement_overlay_data(records, vp_points=vp_points, findings=findings)
    canvas.set_placement_overlay_visible(True)
    assert canvas._placement_overlay_item.isVisible()
    pixmap = canvas._placement_overlay_item.pixmap()
    assert pixmap.width() == canvas.map_w
    assert pixmap.height() == canvas.map_h
    image = pixmap.toImage()
    assert _alpha_count(image) > 0
    model = build_placement_overlay_model(
        records, vp_points=vp_points, findings=findings, width=canvas.map_w, height=canvas.map_h
    )
    kinds = {marker.kind for marker in model.markers}
    assert {"slot", "port", "building", "weather", "vp", "collision"} <= kinds
    for marker in model.markers:
        assert _neighborhood_has_paint(image, marker.x, marker.y)


def test_invalid_data_does_not_crash(small_canvas):
    """Malformed and out-of-bounds inputs are ignored safely."""
    canvas = small_canvas
    records = [
        None,
        "bad",
        {"province_id": 1, "slot": 99, "x": 5.0, "y": 5.0},
        {"province_id": 1, "slot": 0, "x": float("nan"), "y": 5.0},
        {"province_id": 1, "slot": 0, "x": float("inf"), "y": 5.0},
        {"province_id": 1, "slot": 0, "x": 5000.0, "y": 5000.0},
        {"id": 7, "province_id": 2, "building_type": "  ", "x": 6.0, "y": 6.0},
    ]
    vp_points = [None, "bad", (0, 1.0, 2.0), (1, float("nan"), 2.0)]
    findings = [None, "bad", {"code": "placement.collision", "coordinates": "bad"}]
    canvas.set_placement_overlay_data(records, vp_points=vp_points, findings=findings)
    canvas.set_placement_overlay_visible(True)
    pixmap = canvas._placement_overlay_item.pixmap()
    assert pixmap.width() == canvas.map_w
    assert pixmap.height() == canvas.map_h


def test_safe_without_map_data(small_canvas):
    """Overlay API stays safe when map data is not loaded yet."""
    canvas = small_canvas
    saved = canvas._map_data
    canvas._map_data = None
    try:
        records, vp_points, findings = _demo_inputs()
        canvas.set_placement_overlay_data(records, vp_points=vp_points, findings=findings)
        canvas.set_placement_overlay_visible(True)
        assert canvas._placement_overlay_item.isVisible()
        canvas.set_placement_overlay_visible(False)
        assert not canvas._placement_overlay_item.isVisible()
    finally:
        canvas._map_data = saved


def test_vp_overlay_unaffected(small_canvas):
    """Existing VP semantics stay intact alongside the placement overlay."""
    canvas = small_canvas
    canvas._vp_data = {1: 5}
    canvas._vp_cache_dirty = True
    canvas._display_mode = "province"
    canvas._update_vp_visibility()
    assert canvas._vp_overlay_item.isVisible()
    records, vp_points, findings = _demo_inputs()
    canvas.set_placement_overlay_data(records, vp_points=vp_points, findings=findings)
    canvas.set_placement_overlay_visible(True)
    assert canvas._placement_overlay_item.isVisible()
    assert canvas._vp_overlay_item.isVisible()
    assert canvas._placement_overlay_item.zValue() > canvas._vp_overlay_item.zValue()
    canvas.set_placement_overlay_visible(False)
    assert not canvas._placement_overlay_item.isVisible()
    assert canvas._vp_overlay_item.isVisible()
