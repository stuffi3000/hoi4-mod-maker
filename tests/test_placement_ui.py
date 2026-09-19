"""Headless tests for the standalone placement review page (M5.2/M5.3 slice)."""

from types import SimpleNamespace

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QListWidget, QPlainTextEdit, QPushButton

from features.map.placement import PlacementPage, parse_sea_mapping
from features.map.placement import page as placement_page_module
from ui.i18n import tr


def _slot(province_id, slot, **extra):
    fields = {
        "province_id": province_id,
        "slot": slot,
        "x": 1.0,
        "y": 2.0,
        "review_status": "reviewed",
        "provenance": "generated",
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def _port(province_id, sea_province=None, **extra):
    fields = {
        "province_id": province_id,
        "sea_province": sea_province,
        "x": 3.0,
        "y": 4.0,
        "review_status": "unreviewed",
        "provenance": "authored",
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def _click(page, key):
    button = next(
        b for b in page.findChildren(QPushButton) if b.text() == tr(key)
    )
    button.click()
    return button


def test_package_exports():
    assert placement_page_module.PlacementPage is PlacementPage
    assert placement_page_module.parse_sea_mapping is parse_sea_mapping
    assert PlacementPage.parse_sea_mapping is parse_sea_mapping


def test_constructs_headless(qtbot):
    page = PlacementPage()
    qtbot.addWidget(page)
    assert isinstance(page._mapping_edit, QPlainTextEdit)
    assert isinstance(page._records_list, QListWidget)
    assert isinstance(page._review_combo, QComboBox)
    assert [page._review_combo.itemData(i) for i in range(page._review_combo.count())] == [
        "reviewed",
        "accepted",
    ]
    assert page.review_status() == "reviewed"
    texts = {b.text() for b in page.findChildren(QPushButton)}
    assert {
        tr("placement_generate_slots_btn"),
        tr("placement_generate_ports_btn"),
        tr("placement_accept_selected_btn"),
        tr("placement_refresh_btn"),
    } <= texts
    assert page._status_label.text() == tr("placement_status_ready")
    assert page.selected_records() == ([], [])


def test_parse_valid_mapping():
    assert parse_sea_mapping("12:34") == {12: 34}
    assert parse_sea_mapping(" 12 : 34 ") == {12: 34}
    assert parse_sea_mapping("12:34, 56:78") == {12: 34, 56: 78}
    assert parse_sea_mapping("12:34;56:78") == {12: 34, 56: 78}
    assert parse_sea_mapping("12:34\n56:78") == {12: 34, 56: 78}
    assert parse_sea_mapping("12=34") == {12: 34}
    assert parse_sea_mapping("12:34\n") == {12: 34}
    mapping = parse_sea_mapping("12:34, 56:78")
    assert list(mapping.items()) == [(12, 34), (56, 78)]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "7",
        "1-2",
        "a:b",
        "1.5:2",
        "1:2.5",
        "0:5",
        "-1:5",
        "1:0",
        "1:-2",
        "1:2, 1:3",
        "1:2, 1:2",
        "1:2; 1:3",
        "1:2:3",
        ":2",
        "1:",
        "1:2=3",
    ],
)
def test_parse_invalid_mapping(text):
    with pytest.raises(ValueError):
        parse_sea_mapping(text)


@pytest.mark.parametrize("text", [None, 123, ["1:2"], {"1": 2}])
def test_parse_non_string_mapping(text):
    with pytest.raises(ValueError):
        parse_sea_mapping(text)


def test_generate_ports_emits_parsed_mapping(qtbot):
    page = PlacementPage()
    qtbot.addWidget(page)
    page.set_mapping_text("12:34, 56:78")
    with qtbot.waitSignal(page.generate_ports_requested) as blocker:
        _click(page, "placement_generate_ports_btn")
    assert blocker.args == [{12: 34, 56: 78}]
    assert str(2) in page._status_label.text()


@pytest.mark.parametrize("text", ["", "   ", "oops", "7", "1:2, 1:2", "0:5"])
def test_generate_ports_invalid_shows_status_and_emits_nothing(qtbot, text):
    page = PlacementPage()
    qtbot.addWidget(page)
    page.set_mapping_text(text)
    emitted = []
    page.generate_ports_requested.connect(emitted.append)
    _click(page, "placement_generate_ports_btn")
    assert emitted == []
    status = page._status_label.text()
    assert status
    assert tr("placement_error_invalid_mapping") in status


def test_generate_slots_emits_request(qtbot):
    page = PlacementPage()
    qtbot.addWidget(page)
    with qtbot.waitSignal(page.generate_slots_requested):
        _click(page, "placement_generate_slots_btn")
    assert page._status_label.text() == tr("placement_slots_requested")


def test_refresh_emits_request(qtbot):
    page = PlacementPage()
    qtbot.addWidget(page)
    with qtbot.waitSignal(page.refresh_requested):
        _click(page, "placement_refresh_btn")


def test_set_records_orders_and_tags_userrole(qtbot):
    page = PlacementPage()
    qtbot.addWidget(page)
    page.set_records(
        [
            _port(9, 90),
            _slot(5, 2),
            {"province_id": 5, "slot": 0, "x": 0.0, "y": 0.0},
            _port(3, None),
            _slot(2, 1),
            {"province_id": 11, "building_type": "industrial_complex"},
        ]
    )
    assert page._records_list.count() == 5
    payloads = [
        page._records_list.item(row).data(Qt.UserRole) for row in range(5)
    ]
    assert payloads == [
        ("slot", (2, 1)),
        ("slot", (5, 0)),
        ("slot", (5, 2)),
        ("port", 3),
        ("port", 9),
    ]
    assert "2" in page._records_list.item(0).text()
    assert "9" in page._records_list.item(4).text()
    assert page._records_summary.text() == tr("placement_records_summary", 3, 2)
    for row in range(5):
        item = page._records_list.item(row)
        assert item.checkState() == Qt.Unchecked
        assert item.flags() & Qt.ItemIsUserCheckable


def test_set_records_empty_shows_empty_state(qtbot):
    page = PlacementPage()
    qtbot.addWidget(page)
    page.set_records([_slot(2, 1)])
    assert page._records_list.count() == 1
    page.set_records([])
    assert page._records_list.count() == 0
    assert page._records_summary.text() == tr("placement_records_empty")
    page.set_records(None)
    assert page._records_summary.text() == tr("placement_records_empty")


def test_selected_records_and_accept_payload(qtbot):
    page = PlacementPage()
    qtbot.addWidget(page)
    page.set_records([_port(9, 90), _slot(5, 2), _slot(2, 1)])
    page._records_list.item(0).setCheckState(Qt.Checked)
    page._records_list.item(2).setCheckState(Qt.Checked)
    assert page.selected_records() == ([(2, 1)], [9])
    page._review_combo.setCurrentIndex(page._review_combo.findData("accepted"))
    captured = []
    page.accept_selected_requested.connect(
        lambda slots, ports, status: captured.append((slots, ports, status))
    )
    with qtbot.waitSignal(page.accept_selected_requested) as blocker:
        _click(page, "placement_accept_selected_btn")
    assert captured == [([(2, 1)], [9], "accepted")]
    assert blocker.args == [[(2, 1)], [9], "accepted"]


def test_accept_empty_selection_emits_empty_lists(qtbot):
    page = PlacementPage()
    qtbot.addWidget(page)
    page.set_records([_slot(2, 1), _port(9, 90)])
    assert page.selected_records() == ([], [])
    captured = []
    page.accept_selected_requested.connect(
        lambda slots, ports, status: captured.append((slots, ports, status))
    )
    _click(page, "placement_accept_selected_btn")
    assert captured == [([], [], "reviewed")]
    assert page._status_label.text() == tr("placement_accept_empty")


def test_diagnostics_summary_and_clear(qtbot):
    page = PlacementPage()
    qtbot.addWidget(page)
    page.set_diagnostics(
        [
            SimpleNamespace(code="PLACEMENT_NO_SEA", province_id=7, message="boom"),
            SimpleNamespace(code="PLACEMENT_WARN", province_id=8, message="careful"),
        ]
    )
    text = page._diag_label.text()
    assert "2" in text
    assert "PLACEMENT_NO_SEA" in text
    assert "boom" in text
    assert "7" in text
    page.set_diagnostics([SimpleNamespace()])
    assert "issue" in page._diag_label.text()
    page.set_diagnostics([])
    assert page._diag_label.text() == tr("placement_diagnostics_none")
    page.set_diagnostics(None)
    assert page._diag_label.text() == tr("placement_diagnostics_none")


def test_set_status(qtbot):
    page = PlacementPage()
    qtbot.addWidget(page)
    page.set_status("hello")
    assert page._status_label.text() == "hello"
    page.set_status("")
    assert page._status_label.text() == ""
