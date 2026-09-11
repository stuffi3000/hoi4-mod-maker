"""UI and canvas tests for terrain-mode VP controls."""

import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_visual_terrain_page_emits_vp_overlay_toggle(qapp, qtbot):
    from features.map.terrain.page import TerrainPage

    page = TerrainPage()
    qtbot.addWidget(page)
    seen = []
    page.vp_overlay_toggled.connect(seen.append)

    page._vp_overlay_chk.setChecked(True)
    page._vp_overlay_chk.setChecked(False)

    assert seen == [True, False]


def test_attribute_terrain_page_emits_vp_overlay_toggle(qapp, qtbot):
    from features.map.province_terrain.page import ProvincialTerrainPage

    page = ProvincialTerrainPage()
    qtbot.addWidget(page)
    seen = []
    page.vp_overlay_toggled.connect(seen.append)

    page._vp_overlay_chk.setChecked(True)

    assert seen == [True]


def test_vp_overlay_can_be_enabled_per_terrain_mode(qapp, qtbot):
    """The existing VP layer is visible only when its mode-specific toggle is on."""
    import views.canvas.widget as widget_mod
    import data.constants as constants
    from data.constants import set_map_size

    old_w, old_h = constants.MAP_WIDTH, constants.MAP_HEIGHT
    set_map_size(widget_mod.MAP_WIDTH, widget_mod.MAP_HEIGHT)
    try:
        canvas = widget_mod.MapCanvas()
        qtbot.addWidget(canvas)
        canvas._vp_data = {1: 5}
        canvas._vp_cache_dirty = False

        canvas._display_mode = "terrain"
        canvas.set_vp_overlay_visible("terrain", True)
        assert canvas._vp_overlay_item.isVisible()

        canvas._display_mode = "province_terrain"
        canvas.set_vp_overlay_visible("province_terrain", False)
        assert not canvas._vp_overlay_item.isVisible()
        canvas.set_vp_overlay_visible("province_terrain", True)
        assert canvas._vp_overlay_item.isVisible()
    finally:
        set_map_size(old_w, old_h)
