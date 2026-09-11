"""OptionChooserDialog — "Speaking multiple choice questions" dialog box.

To solve the problem of "too many buttons and I don't know which one to click": There is only one entry button left on the page. After clicking it, each option is
A large card (title + a sentence explaining when to use it), click on the card to select it.

Usage:
    key = OptionChooserDialog.choose(parent, "Generate/Optimize Height", [
        ("realistic", "Generate real terrain from scratch", "I haven't drawn the height yet..."),
        ("refine", "Conformal Refinement", "I have already drawn where it is high and where it is low..."),
    ])
    if key == "realistic": ..."""

from __future__ import annotations

from typing import Callable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QFrame,
)

from ui.i18n import tr
from ui.styles import _BORDER, _TEXT, _DIM, _ACCENT, _INPUT_BG

# Cards use QFrame instead of QPushButton: the height of QPushButton will not follow the interior
# The wrapped text grows taller (the text is cropped), and QFrame + layout can correctly calculate the height according to the content.
_CARD_STYLE = f"""
    QFrame#optionCard {{
        background: {_INPUT_BG};
        border: 1px solid {_BORDER};
        border-radius: 6px;
    }}
    QFrame#optionCard:hover {{
        border: 1px solid {_ACCENT};
        background: rgba(79, 140, 255, 0.12);
    }}
"""


class _OptionCard(QFrame):
    """A clickable tab: title + line break description."""

    def __init__(self, key: str, name: str, desc: str,
                 on_pick: Callable[[str], None]) -> None:
        super().__init__()
        self._key = key
        self._on_pick = on_pick
        self.setObjectName("optionCard")
        self.setStyleSheet(_CARD_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f"background: transparent; color: {_TEXT};"
            " font-size: 14px; font-weight: 700;")
        v.addWidget(name_lbl)

        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(
            f"background: transparent; color: {_DIM}; font-size: 12px;")
        v.addWidget(desc_lbl)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_pick(self._key)
        super().mouseReleaseEvent(event)


class OptionChooserDialog(QDialog):
    """Large card radio dialog box. The selected key is stored in self.selected."""

    def __init__(self, parent, title: str,
                 options: list[tuple[str, str, str]]) -> None:
        super().__init__(parent)
        self.selected: str | None = None
        self.setWindowTitle(title)
        # Fixed width: The description text wraps at a known width so that the height can be calculated correctly
        self.setFixedWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        for key, name, desc in options:
            lay.addWidget(_OptionCard(key, name, desc, self._pick))

        cancel = QPushButton(tr("btn_cancel"))
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignRight)

        # The height is pinned to "content height at width 460": leaving no extra space for the layout to allocate,
        # Otherwise, a large gap will be drawn between the cards; only heightForWidth can be used to calculate the height of the wrapped text.
        lay.activate()
        if lay.hasHeightForWidth():
            self.setFixedHeight(lay.heightForWidth(self.width()))
        else:
            self.setFixedHeight(self.sizeHint().height())

    def _pick(self, key: str) -> None:
        self.selected = key
        self.accept()

    @staticmethod
    def choose(parent, title: str,
               options: list[tuple[str, str, str]]) -> str | None:
        """A dialog box pops up, returning the selected key; canceling returns None.

        parent can pass any control (such as sidebar page) - internally, its top-level window is used as the anchor point.
        And explicitly centered: directly using the sidebar widget as the parent will cause the dialog box to pop up in a strange position."""
        anchor = parent.window() if parent is not None else None
        dlg = OptionChooserDialog(anchor, title, options)
        dlg.adjustSize()
        if anchor is not None:
            dlg.move(anchor.frameGeometry().center() - dlg.rect().center())
        dlg.exec_()
        return dlg.selected
