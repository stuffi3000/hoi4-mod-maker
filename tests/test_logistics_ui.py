from types import SimpleNamespace

from PyQt5.QtCore import Qt
from domain.managers.strategic_region import StrategicRegionManager
from features.map.strategic_region.page import StrategicRegionPage
from features.map.logistics.page import LogisticsPage
from views.main_window_actions import MainWindowActionsMixin
from ui.i18n import tr
from ui.tool_panel import _SubModeTabBar


def test_logistics_navigation_menu_includes_placements():
    assert tr("nav_logistics") == "Logistics and Placements"


def test_strategic_region_refresh_populates_and_preserves_selection(qtbot):
    page = StrategicRegionPage()
    qtbot.addWidget(page)
    manager = StrategicRegionManager()
    manager.create_region("Belgium").province_ids = [1, 2]
    manager.create_region("North Sea").province_ids = [3]
    selected = []
    window = SimpleNamespace(
        _tool_panel=SimpleNamespace(_sr_list=page._sr_list),
        _project=SimpleNamespace(strategic_region_mgr=manager),
        _on_sr_selected=selected.append,
    )
    MainWindowActionsMixin._refresh_sr_list(window)
    assert page._sr_list.count() == 2
    assert "Belgium" in page._sr_list.item(0).text()
    page._sr_list.setCurrentRow(1)
    MainWindowActionsMixin._refresh_sr_list(window)
    assert page._sr_list.currentItem().data(Qt.UserRole) == 2
    assert selected[-1] == 1


def test_logistics_generation_button_emits_request(qtbot):
    from PyQt5.QtWidgets import QPushButton
    page = LogisticsPage()
    qtbot.addWidget(page)
    button = next(b for b in page.findChildren(QPushButton)
                  if b.text() == tr("logistics_generate_button"))
    with qtbot.waitSignal(page.generate_logistics_requested):
        button.click()


def test_logistics_help_and_background_selector(qtbot):
    from PyQt5.QtWidgets import QLabel

    page = LogisticsPage()
    qtbot.addWidget(page)

    labels = "\n".join(label.text() for label in page.findChildren(QLabel))
    assert "left-click" in labels
    assert "yellow-gold" in labels
    assert "Generate Logistics" in labels

    assert page._background_combo.count() == 3
    assert page._background_combo.itemData(0) == "dark"
    assert page._background_combo.itemData(1) == "terrain"
    assert page._background_combo.itemData(2) == "countries"


def test_logistics_background_selector_emits_value(qtbot):
    page = LogisticsPage()
    qtbot.addWidget(page)
    received = []
    page.logistics_background_changed.connect(received.append)

    page._background_combo.setCurrentIndex(1)
    assert received == ["terrain"]

    page._background_combo.setCurrentIndex(2)
    assert received == ["terrain", "countries"]


def test_logistics_group_status_dots_reflect_feature_readiness(qtbot):
    bar = _SubModeTabBar()
    qtbot.addWidget(bar)
    tabs = [
        ("strategic_region", "tab_strategic_region", "🟠"),
        ("logistics", "tab_logistics", "🟠"),
    ]
    bar.set_tabs(tabs)
    assert bar._buttons[0].text().startswith("🟠")
    assert bar._buttons[1].text().startswith("🟠")

    bar.set_feature_ready("strategic_region", True)
    bar.set_feature_ready("logistics", True)
    assert bar._buttons[0].text().startswith("🟢")
    assert bar._buttons[1].text().startswith("🟢")

    # Switching away and back recreates the buttons; readiness persists.
    bar.set_tabs([("land", "tab_land", "🟢")])
    bar.set_tabs(tabs)
    assert all(button.text().startswith("🟢") for button in bar._buttons)

    bar.set_feature_ready("logistics", False)
    assert bar._buttons[1].text().startswith("🟠")
