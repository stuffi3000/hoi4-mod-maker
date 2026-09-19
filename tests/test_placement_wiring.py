"""Focused tests for placement page/controller application wiring."""

from types import SimpleNamespace
import inspect

from PyQt5.QtCore import Qt

from controllers.app_controller import ApplicationController
from controllers.placement import PlacementController
from features.map.placement import PlacementPage
from ui.tool_panel import ToolPanel
from views.main_window import MainWindow


def test_tool_panel_registers_placement_page_and_forwards_signals(qtbot):
    panel = ToolPanel()
    qtbot.addWidget(panel)

    assert "placement" in panel._pages
    assert panel._pages["placement"] is panel._placement_page
    assert panel._sub_to_nav["placement"] == "logistics_group"

    forwarded = []
    panel.placement_generate_slots_requested.connect(
        lambda: forwarded.append(("slots",))
    )
    panel.placement_generate_ports_requested.connect(
        lambda mapping: forwarded.append(("ports", mapping))
    )
    panel.placement_accept_selected_requested.connect(
        lambda slots, ports, status: forwarded.append(
            ("accept", slots, ports, status)
        )
    )
    panel.placement_refresh_requested.connect(
        lambda: forwarded.append(("refresh",))
    )

    page = panel._placement_page
    page.generate_slots_requested.emit()
    page.generate_ports_requested.emit({1: 2})
    page.accept_selected_requested.emit([(1, 0)], [1], "reviewed")
    page.refresh_requested.emit()

    assert forwarded == [
        ("slots",),
        ("ports", {1: 2}),
        ("accept", [(1, 0)], [1], "reviewed"),
        ("refresh",),
    ]


def test_tool_panel_forwards_placement_transform_signals(qtbot):
    panel = ToolPanel()
    qtbot.addWidget(panel)

    updates = []
    resets = []
    panel.placement_transform_update_requested.connect(
        lambda kind, key, x, y, rotation, height: updates.append(
            (kind, key, x, y, rotation, height)
        )
    )
    panel.placement_transform_reset_requested.connect(
        lambda kind, key: resets.append((kind, key))
    )

    page = panel._placement_page
    transform_key = (5, 2)
    page.transform_update_requested.emit("slot", transform_key, 1.5, 2.5, 30.25, 3.75)
    page.transform_reset_requested.emit("port", 9)

    assert updates == [("slot", transform_key, 1.5, 2.5, 30.25, 3.75)]
    assert updates[0][1] is transform_key
    assert resets == [("port", 9)]


def test_tool_panel_switches_to_placement_mode(qtbot):
    panel = ToolPanel()
    qtbot.addWidget(panel)
    seen = []
    panel.mode_changed.connect(seen.append)

    panel._switch_to_mode("placement")

    assert panel._stack.currentWidget() is panel._placement_page
    assert seen[-1] == "placement"
    assert panel._sub_tabs._buttons
    assert any(
        button.property("sub_mode_id") == "placement"
        for button in panel._sub_tabs._buttons
    )


def test_application_controller_uses_safe_canvas_mode_for_placement():
    refreshes = []
    fake_controller = SimpleNamespace(activate=lambda: None, deactivate=lambda: None)
    canvas = SimpleNamespace(
        display_mode="land",
        _highlight_country_rgb=None,
        cleanup_mode_state=lambda: None,
        set_density_overlay_visible=lambda visible: None,
        show_state_borders=lambda visible: None,
    )
    app = object.__new__(ApplicationController)
    app._current_controller = None
    app._canvas = canvas
    app._project = SimpleNamespace(map_data=SimpleNamespace())
    app._controllers = {"placement": fake_controller, "land": None}
    app._refresh_sr_colors = lambda: refreshes.append(True)

    label = app.on_mode_changed("placement")

    assert canvas.display_mode == "strategic_region"
    assert app.current_controller is fake_controller
    assert refreshes == [True]
    assert label


def test_main_window_registers_placement_controller_and_routes_page():
    code = MainWindow.__init__.__code__
    assert "PlacementController" in code.co_names
    assert '"placement"' in inspect.getsource(MainWindow.__init__)
    assert ApplicationController._MODE_KEYS["placement"] == "mode_placement"
    assert PlacementController.__name__ == "PlacementController"
    assert PlacementPage.__name__ == "PlacementPage"
