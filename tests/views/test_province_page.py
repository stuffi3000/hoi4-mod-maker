"""Province-page generation controls and ordering tests."""
from __future__ import annotations

from PyQt5.QtWidgets import QGroupBox

from features.map.province.page import ProvincePage
from ui.i18n import set_language


def test_generation_section_precedes_manual_drawing(qtbot):
    set_language("en")
    page = ProvincePage()
    qtbot.addWidget(page)

    sections = [
        item.widget().title()
        for index in range(page.layout().count())
        if isinstance((item := page.layout().itemAt(index)).widget(), QGroupBox)
    ]
    assert sections.index("Province Generation") < sections.index("Manual Province Drawing")


def test_generation_buttons_emit_scope_and_target_count(qtbot):
    page = ProvincePage()
    qtbot.addWidget(page)
    page._province_count_spin.setValue(3750)
    emitted: list[tuple[str, int]] = []
    page.generate_provinces_requested.connect(
        lambda scope, count: emitted.append((scope, count))
    )

    for scope in ("all", "land", "sea", "lake"):
        page._generation_buttons[scope].click()

    assert emitted == [("all", 3750), ("land", 3750), ("sea", 3750), ("lake", 3750)]


def test_validate_button_is_on_province_page(qtbot):
    page = ProvincePage()
    qtbot.addWidget(page)
    emitted: list[bool] = []
    page.validate_requested.connect(lambda: emitted.append(True))

    page._validate_btn.click()

    assert emitted == [True]
