"""Regression tests for the Countries → Continent page."""

from types import SimpleNamespace

from PyQt5.QtCore import Qt

from domain.managers.continent import ContinentManager
from features.map.continent.page import ContinentPage
from views.main_window import MainWindow
from views.main_window_actions import MainWindowActionsMixin


def test_entering_continent_mode_refreshes_existing_continents(qtbot):
    page = ContinentPage()
    qtbot.addWidget(page)

    manager = ContinentManager()
    manager.rename_continent(0, "Europe")
    window = SimpleNamespace(
        _app=SimpleNamespace(on_mode_changed=lambda mode: mode),
        _status_mode=SimpleNamespace(setText=lambda _text: None),
        _canvas=None,
        _tool_panel=SimpleNamespace(_placement_page=None),
        _refresh_feature_statuses=lambda: None,
        _project=SimpleNamespace(continent_mgr=manager),
    )
    window._tool_panel._continent_list = page._continent_list
    window._refresh_continent_list = MainWindowActionsMixin._refresh_continent_list.__get__(window)

    assert page._continent_list.count() == 0
    MainWindow._on_mode_changed(window, "continent")

    assert page._continent_list.count() == 1
    item = page._continent_list.item(0)
    assert item.data(Qt.UserRole) == "Europe"
    assert item.text().startswith("1. Europe")
