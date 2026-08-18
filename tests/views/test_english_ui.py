"""Regression coverage for Chinese text leaking into the English interface."""

import re

from PyQt5.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QSpinBox,
    QTabWidget,
    QWidget,
)

from ui.i18n import set_language
from ui.tool_panel import ToolPanel


CHINESE_TEXT = re.compile(r"[\u3400-\u9fff]")


def _record_if_chinese(offenders, widget, field, value):
    if isinstance(value, str) and CHINESE_TEXT.search(value):
        offenders.append((type(widget).__name__, field, value))


def test_tool_panel_contains_only_english_text_in_english_mode(qtbot):
    set_language("en")
    panel = ToolPanel()
    qtbot.addWidget(panel)

    offenders = []
    widgets = [panel, *panel.findChildren(QWidget)]
    for widget in widgets:
        for field in ("windowTitle", "toolTip", "statusTip", "whatsThis"):
            _record_if_chinese(offenders, widget, field, getattr(widget, field)())

        if isinstance(widget, (QAbstractButton, QLabel)):
            _record_if_chinese(offenders, widget, "text", widget.text())
        if isinstance(widget, QGroupBox):
            _record_if_chinese(offenders, widget, "title", widget.title())
        if isinstance(widget, QLineEdit):
            _record_if_chinese(
                offenders, widget, "placeholderText", widget.placeholderText()
            )
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            _record_if_chinese(offenders, widget, "prefix", widget.prefix())
            _record_if_chinese(offenders, widget, "suffix", widget.suffix())
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                _record_if_chinese(
                    offenders, widget, f"itemText[{index}]", widget.itemText(index)
                )
        if isinstance(widget, QListWidget):
            for index in range(widget.count()):
                _record_if_chinese(
                    offenders, widget, f"item[{index}]", widget.item(index).text()
                )
        if isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                _record_if_chinese(
                    offenders, widget, f"tabText[{index}]", widget.tabText(index)
                )

    assert not offenders, f"Chinese text found in English UI: {offenders}"
