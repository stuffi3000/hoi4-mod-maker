"""Focused tests for placement page/controller application wiring."""

from types import SimpleNamespace
import inspect

from PyQt5.QtCore import Qt

from controllers.app_controller import ApplicationController
from controllers.placement import PlacementController
from features.map.placement import PlacementPage
from ui.tool_panel import ToolPanel
from ui.i18n import tr
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
class _FakeReplacePage:
    def __init__(self, replace_value=False):
        self._replace_value = bool(replace_value)
        self.diagnostics_calls = []
        self.status_calls = []

    def replace_generated(self):
        return self._replace_value

    def set_diagnostics(self, diagnostics):
        self.diagnostics_calls.append(list(diagnostics))

    def set_status(self, text):
        self.status_calls.append(text)


class _FakeBusyPage(_FakeReplacePage):
    def __init__(self, replace_value=False):
        super().__init__(replace_value=replace_value)
        self.busy_calls = []

    def set_generation_busy(self, busy):
        self.busy_calls.append(bool(busy))


class _FakeProgressBar:
    def __init__(self):
        self.range_calls = []
        self.visible_calls = []

    def setRange(self, minimum, maximum):
        self.range_calls.append((minimum, maximum))

    def setVisible(self, visible):
        self.visible_calls.append(bool(visible))


class _FakeStatusLabel:
    def __init__(self):
        self.texts = []

    def setText(self, text):
        self.texts.append(text)


class _FakeLegacyPage:
    def __init__(self):
        self.diagnostics_calls = []
        self.status_calls = []

    def set_diagnostics(self, diagnostics):
        self.diagnostics_calls.append(list(diagnostics))

    def set_status(self, text):
        self.status_calls.append(text)


class _FakeProposalController:
    def __init__(self):
        self.slot_kwargs = None
        self.port_args = None
        self.port_kwargs = None

    def propose_slots(self, **kwargs):
        self.slot_kwargs = dict(kwargs)
        return SimpleNamespace(
            diagnostics=[],
            store_report=SimpleNamespace(stored_count=1, skipped_count=0),
        )

    def propose_ports(self, sea_mapping, **kwargs):
        self.port_args = sea_mapping
        self.port_kwargs = dict(kwargs)
        return SimpleNamespace(
            diagnostics=[],
            store_report=SimpleNamespace(stored_count=1, skipped_count=0),
        )


def _make_generate_self(page, controller):
    refresh_calls = []
    fake_self = SimpleNamespace(
        _tool_panel=SimpleNamespace(_placement_page=page),
        _controllers={"placement": controller},
        _refresh_placement_page=lambda: refresh_calls.append(True),
    )
    return fake_self, refresh_calls


def test_main_window_forwards_replace_false_to_propose_slots():
    page = _FakeReplacePage(replace_value=False)
    controller = _FakeProposalController()
    fake_self, refresh_calls = _make_generate_self(page, controller)
    MainWindow._on_placement_generate_slots(fake_self)
    assert controller.slot_kwargs == {"replace_generated": False}
    assert refresh_calls == [True]
    assert page.diagnostics_calls == [[]]


def test_main_window_forwards_replace_true_to_propose_slots():
    page = _FakeReplacePage(replace_value=True)
    controller = _FakeProposalController()
    fake_self, refresh_calls = _make_generate_self(page, controller)
    MainWindow._on_placement_generate_slots(fake_self)
    assert controller.slot_kwargs == {"replace_generated": True}
    assert refresh_calls == [True]


def test_main_window_forwards_replace_to_propose_ports():
    for flag in (False, True):
        page = _FakeReplacePage(replace_value=flag)
        controller = _FakeProposalController()
        fake_self, refresh_calls = _make_generate_self(page, controller)
        MainWindow._on_placement_generate_ports(fake_self, {12: 34})
        assert controller.port_args == {12: 34}
        assert controller.port_kwargs == {"replace_generated": flag}
        assert refresh_calls == [True]


def test_placement_generation_shows_and_clears_footer_feedback():
    cases = (
        (
            MainWindow._on_placement_generate_slots,
            (),
            "placement_slots_generating",
        ),
        (
            MainWindow._on_placement_generate_ports,
            ({12: 34},),
            "placement_ports_generating",
        ),
    )
    for handler, args, message_key in cases:
        page = _FakeBusyPage()
        controller = _FakeProposalController()
        fake_self, refresh_calls = _make_generate_self(page, controller)
        progress = _FakeProgressBar()
        status = _FakeStatusLabel()
        fake_self._placement_progress_bar = progress
        fake_self._status_info = status

        handler(fake_self, *args)

        assert refresh_calls == [True]
        assert page.busy_calls == [True, False]
        assert progress.visible_calls == [True, False]
        assert progress.range_calls == [(0, 0)]
        assert status.texts == [tr(message_key), tr("status_ready")]


def test_main_window_preserves_legacy_page_without_replace_method():
    for handler, kwargs in (
        (MainWindow._on_placement_generate_slots, {}),
        (MainWindow._on_placement_generate_ports, {"sea_mapping": {1: 2}}),
    ):
        page = _FakeLegacyPage()
        controller = _FakeProposalController()
        fake_self, refresh_calls = _make_generate_self(page, controller)
        if kwargs:
            handler(fake_self, kwargs["sea_mapping"])
            assert controller.port_args == {1: 2}
            assert controller.port_kwargs == {"replace_generated": False}
        else:
            handler(fake_self)
            assert controller.slot_kwargs == {"replace_generated": False}
        assert refresh_calls == [True]


def test_placement_replace_helper_defaults_false_for_legacy_and_errors():
    assert MainWindow._placement_replace_generated(object()) is False
    assert MainWindow._placement_replace_generated(SimpleNamespace()) is False

    def _boom():
        raise RuntimeError("boom")

    assert MainWindow._placement_replace_generated(SimpleNamespace(replace_generated=_boom)) is False
    assert MainWindow._placement_replace_generated(SimpleNamespace(replace_generated=lambda: True)) is True
    assert MainWindow._placement_replace_generated(SimpleNamespace(replace_generated=lambda: 1)) is True
