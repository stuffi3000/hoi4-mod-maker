"""Onboarding Dialog - Shows a 6-step workflow overview after creating a new project."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QWidget, QSizePolicy,
)
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QFont

from ui.i18n import tr

_BG = "#17181c"
_INPUT_BG = "#1f2126"
_BORDER = "#2c2f36"
_TEXT = "#e8eaed"
_DIM = "#9aa0ab"
_ACCENT = "#4f8cff"

_SETTINGS_KEY = "GuideDialog/dont_show"

# 6 steps: (icon, title_key, desc_key)
_STEPS = [
    ("\U0001F3D6", "guide_step1_title", "guide_step1_desc"),   # 🏖 Draw the continent
    ("\U0001F9E9", "guide_step2_title", "guide_step2_desc"),   # 🧩 Generate provinces
    ("\U000026F0", "guide_step3_title", "guide_step3_desc"),   # ⛰ Terrain height
    ("\U0001F3F3", "guide_step4_title", "guide_step4_desc"),   # 🏳Statehood
    ("\U0001F6E4", "guide_step5_title", "guide_step5_desc"),   # 🛤 Logistics
    ("\U0001F680", "guide_step6_title", "guide_step6_desc"),   # 🚀 Export
]


def should_show_guide() -> bool:
    """Check whether display boot is required."""
    return not QSettings("HOI4MapMaker", "Guide").value(_SETTINGS_KEY, False, type=bool)


class GuideDialog(QDialog):
    """Step-by-step workflow guidance dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("guide_title"))
        # Long translations may stretch the dialog box, allowing expansion + user dragging to adjust
        self.setMinimumSize(520, 400)
        self.resize(520, 400)
        self.setStyleSheet(f"""
            QDialog {{
                background: {_BG};
                color: {_TEXT};
            }}
        """)
        self._current = 0
        self._init_ui()
        self._refresh()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # title bar
        header = QLabel(tr("guide_title"))
        _hf = QFont("Segoe UI", 16, QFont.Weight.Bold)
        _hf.setFamilies(["Segoe UI", "Arial", "sans-serif"])
        header.setFont(_hf)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(f"""
            color: {_TEXT};
            padding: 20px;
            background: {_INPUT_BG};
            border-bottom: 1px solid {_BORDER};
        """)
        root.addWidget(header)

        # Content area: Step list on the left + details on the right
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Left step navigation
        self._step_labels: list[QLabel] = []
        left = QWidget()
        left.setMinimumWidth(160)
        left.setStyleSheet(f"background: {_INPUT_BG}; border-right: 1px solid {_BORDER};")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 12, 0, 12)
        left_lay.setSpacing(0)

        for i, (icon, title_key, _) in enumerate(_STEPS):
            lbl = QLabel(f"  {icon} {tr(title_key)}")
            lbl.setFixedHeight(36)
            lbl.setStyleSheet(f"color: {_DIM}; font-size: 13px; padding-left: 12px;")
            left_lay.addWidget(lbl)
            self._step_labels.append(lbl)
        left_lay.addStretch()
        body.addWidget(left)

        # Details on the right
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(24, 24, 24, 16)
        right_lay.setSpacing(12)

        self._step_num = QLabel()
        _nf = QFont("Segoe UI", 12, QFont.Weight.Bold)
        _nf.setFamilies(["Segoe UI", "Arial", "sans-serif"])
        self._step_num.setFont(_nf)
        self._step_num.setStyleSheet(f"color: {_ACCENT};")
        right_lay.addWidget(self._step_num)

        self._step_title = QLabel()
        _tf = QFont("Segoe UI", 15, QFont.Weight.Bold)
        _tf.setFamilies(["Segoe UI", "Arial", "sans-serif"])
        self._step_title.setFont(_tf)
        self._step_title.setStyleSheet(f"color: {_TEXT};")
        self._step_title.setWordWrap(True)
        right_lay.addWidget(self._step_title)

        self._step_desc = QLabel()
        self._step_desc.setStyleSheet(f"color: {_DIM}; font-size: 13px; line-height: 1.6;")
        self._step_desc.setWordWrap(True)
        self._step_desc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._step_desc.setAlignment(Qt.AlignmentFlag.AlignTop)
        right_lay.addWidget(self._step_desc, 1)

        body.addWidget(right, 1)
        root.addLayout(body, 1)

        # bottom button bar
        footer = QWidget()
        footer.setStyleSheet(f"background: {_INPUT_BG}; border-top: 1px solid {_BORDER};")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(16, 10, 16, 10)

        self._dont_show = QCheckBox(tr("guide_dont_show"))
        self._dont_show.setStyleSheet(f"color: {_DIM}; font-size: 12px;")
        footer_lay.addWidget(self._dont_show)

        footer_lay.addStretch()

        btn_style = f"""
            QPushButton {{
                background: {_INPUT_BG};
                border: 1px solid {_BORDER};
                color: {_TEXT};
                padding: 6px 20px;
                border-radius: 4px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                border-color: {_ACCENT};
                background: rgba(79, 140, 255, 0.12);
            }}
            QPushButton:disabled {{
                color: {_BORDER};
            }}
        """
        start_btn_style = f"""
            QPushButton {{
                background: {_ACCENT};
                border: none;
                color: white;
                padding: 6px 20px;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #6ba1ff;
            }}
        """

        self._btn_prev = QPushButton(tr("guide_prev"))
        self._btn_prev.setStyleSheet(btn_style)
        self._btn_prev.clicked.connect(self._prev)
        footer_lay.addWidget(self._btn_prev)

        self._btn_next = QPushButton(tr("guide_next"))
        self._btn_next.setStyleSheet(btn_style)
        self._btn_next.clicked.connect(self._next)
        footer_lay.addWidget(self._btn_next)

        self._btn_start = QPushButton(tr("guide_start"))
        self._btn_start.setStyleSheet(start_btn_style)
        self._btn_start.clicked.connect(self.accept)
        footer_lay.addWidget(self._btn_start)

        root.addWidget(footer)

    def _refresh(self) -> None:
        """Refresh the current step display."""
        icon, title_key, desc_key = _STEPS[self._current]

        self._step_num.setText(tr("guide_step_n", self._current + 1, len(_STEPS)))
        self._step_title.setText(f"{icon}  {tr(title_key)}")
        self._step_desc.setText(tr(desc_key))

        # Highlight current step
        for i, lbl in enumerate(self._step_labels):
            if i == self._current:
                lbl.setStyleSheet(
                    f"color: white; font-size: 13px; font-weight: bold;"
                    f" padding-left: 12px; background: rgba(79, 140, 255, 0.2);"
                    f" border-left: 3px solid {_ACCENT};"
                )
            else:
                lbl.setStyleSheet(f"color: {_DIM}; font-size: 13px; padding-left: 12px;")

        self._btn_prev.setEnabled(self._current > 0)
        is_last = self._current == len(_STEPS) - 1
        self._btn_next.setVisible(not is_last)
        self._btn_start.setVisible(is_last)

    def _prev(self) -> None:
        if self._current > 0:
            self._current -= 1
            self._refresh()

    def _next(self) -> None:
        if self._current < len(_STEPS) - 1:
            self._current += 1
            self._refresh()

    def accept(self) -> None:
        if self._dont_show.isChecked():
            QSettings("HOI4MapMaker", "Guide").setValue(_SETTINGS_KEY, True)
        super().accept()
