"""River Edit Page — New UI: 🪄 One-click generation + ✏️ Manual 3-step guide."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QButtonGroup, QGridLayout,
)

from domain.managers.river import (
    RIVER_MARKER_TYPES, RIVER_WIDTH_TYPES, RIVER_PALETTE,
    RIVER_WIDTH_4,  # Default width: Middle River (index 6)
)

from ui.styles import (
    make_section as _make_section,
    _DIM, _TEXT, _ACCENT, _SECTION_STYLE, _LABEL_STYLE, _DIM_LABEL_STYLE,
    _SLIDER_STYLE, _TOOL_BTN_STYLE, _SECONDARY_BTN_STYLE, _PRIMARY_BTN_STYLE,
)
from ui.i18n import tr


class RiverPage(QWidget):
    """River edit page - new layout (automatic + manual 3 steps)."""

    # Output signal
    tool_changed = pyqtSignal(str)
    brush_size_changed = pyqtSignal(int)
    river_type_changed = pyqtSignal(int)
    validate_river_requested = pyqtSignal()
    auto_hydrology_from_ref_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        auto_box = _make_section(tr("river_section_auto_reference"))
        auto_hint = QLabel(tr("river_auto_reference_hint"))
        auto_hint.setWordWrap(True)
        auto_hint.setStyleSheet(_DIM_LABEL_STYLE)
        auto_box.layout().addWidget(auto_hint)
        auto_btn = QPushButton(tr("river_btn_auto_reference"))
        auto_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        auto_btn.setToolTip(tr("river_btn_auto_reference_tip"))
        auto_btn.clicked.connect(self.auto_hydrology_from_ref_requested.emit)
        auto_box.layout().addWidget(auto_btn)
        lay.addWidget(auto_box)

        # ═══════════════════ ✏️ Hand drawn river ═══════════════════
        manual_box = _make_section(tr("river_section_manual"))
        manual_layout = manual_box.layout()

        # ── Step 1: Select width ──
        step1 = QLabel(tr("river_step1_title"))
        step1.setStyleSheet(f"color: {_TEXT}; font-size: 14px; padding: 2px;")
        step1.setTextFormat(Qt.TextFormat.RichText)
        manual_layout.addWidget(step1)

        wgrid = QGridLayout()
        wgrid.setSpacing(4)
        self._width_group = QButtonGroup(self)
        self._width_group.setExclusive(True)
        for i, (idx, name_key) in enumerate(RIVER_WIDTH_TYPES):
            r, g, b = RIVER_PALETTE[idx]
            label = tr(name_key)
            btn = _make_river_btn(label, r, g, b)
            btn.setCheckable(True)
            btn.setProperty("river_idx", idx)
            btn.setToolTip(tr("river_width_tip_fmt").format(label, idx))
            self._width_group.addButton(btn, idx)
            btn.clicked.connect(lambda _, ix=idx: self._on_width_clicked(ix))
            wgrid.addWidget(btn, i // 4, i % 4)
        manual_layout.addLayout(wgrid)

        # "Middle River" is selected by default
        default_btn = self._width_group.button(RIVER_WIDTH_4)
        if default_btn:
            default_btn.setChecked(True)

        # ── Step 2: Draw the river ──
        step2 = QLabel(tr("river_step2_title"))
        step2.setStyleSheet(f"color: {_TEXT}; font-size: 14px; padding: 6px 2px 2px 2px;")
        step2.setTextFormat(Qt.TextFormat.RichText)
        manual_layout.addWidget(step2)

        step2_hint = QLabel(tr("river_step2_hint"))
        step2_hint.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 2px;")
        step2_hint.setWordWrap(True)
        manual_layout.addWidget(step2_hint)

        # ── Step 3: Add mark ──
        step3 = QLabel(tr("river_step3_title"))
        step3.setStyleSheet(f"color: {_TEXT}; font-size: 14px; padding: 6px 2px 2px 2px;")
        step3.setTextFormat(Qt.TextFormat.RichText)
        manual_layout.addWidget(step3)

        # marker button + corresponding tooltip key
        _MARKER_TIP_KEYS = {
            "river_marker_source": "river_marker_source_tip",
            "river_marker_confluence": "river_marker_confluence_tip",
            "river_marker_mouth": "river_marker_mouth_tip",
        }
        mgrid = QGridLayout()
        mgrid.setSpacing(4)
        self._marker_group = QButtonGroup(self)
        self._marker_group.setExclusive(True)
        for i, (idx, name_key) in enumerate(RIVER_MARKER_TYPES):
            r, g, b = RIVER_PALETTE[idx]
            btn = _make_river_btn(tr(name_key), r, g, b)
            btn.setCheckable(True)
            btn.setProperty("river_idx", idx)
            tip_key = _MARKER_TIP_KEYS.get(name_key)
            if tip_key:
                btn.setToolTip(tr(tip_key))
            self._marker_group.addButton(btn, idx)
            btn.clicked.connect(lambda _, ix=idx: self._on_marker_clicked(ix))
            mgrid.addWidget(btn, 0, i)
        manual_layout.addLayout(mgrid)

        step3_hint = QLabel(tr("river_step3_hint"))
        step3_hint.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 2px;")
        step3_hint.setWordWrap(True)
        manual_layout.addWidget(step3_hint)

        # Validation button — moved to the end of the manual section (the natural position where the user has finished drawing the river)
        validate_btn = QPushButton(tr("river_btn_validate_new"))
        validate_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        validate_btn.setToolTip(tr("river_validate_tooltip"))
        validate_btn.clicked.connect(self.validate_river_requested.emit)
        manual_layout.addWidget(validate_btn)

        lay.addWidget(manual_box)

        # ═══════════════════ Tools: Brush/Eraser (middle button already supports panning, pan deletion button) ═══════════════════
        tools_box = _make_section(tr("section_tools"))
        tl = QHBoxLayout()
        self._river_tool_group = QButtonGroup(self)
        self._river_tool_group.setExclusive(True)
        for tid, label in [("brush", tr("river_brush_btn")), ("eraser", tr("river_eraser_btn"))]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("tool_id", tid)
            btn.setStyleSheet(_TOOL_BTN_STYLE)
            btn.setMinimumWidth(48)
            self._river_tool_group.addButton(btn)
            tl.addWidget(btn)
            if tid == "brush":
                btn.setChecked(True)
        self._river_tool_group.buttonClicked.connect(
            lambda b: self.tool_changed.emit(b.property("tool_id"))
        )
        tools_box.layout().addLayout(tl)

        # Eraser size (brush defaults to 1px, not adjustable - HOI4 rivers must be 1 pixel wide)
        size_row = QHBoxLayout()
        size_lbl = QLabel(tr("river_eraser_range"))
        size_lbl.setStyleSheet(_LABEL_STYLE)
        self._river_brush_label = QLabel(tr("river_eraser_label_fmt").format(1))
        self._river_brush_label.setStyleSheet(_DIM_LABEL_STYLE)
        size_row.addWidget(size_lbl)
        size_row.addStretch()
        size_row.addWidget(self._river_brush_label)
        tools_box.layout().addLayout(size_row)

        self._river_brush_slider = QSlider(Qt.Orientation.Horizontal)
        self._river_brush_slider.setRange(1, 20)
        self._river_brush_slider.setValue(1)  # Default 1px (the brush is also drawn at 1px, which only affects the eraser)
        self._river_brush_slider.setStyleSheet(_SLIDER_STYLE)
        self._river_brush_slider.valueChanged.connect(self._on_river_brush)
        tools_box.layout().addWidget(self._river_brush_slider)

        slider_tip = QLabel(tr("river_width_note"))
        slider_tip.setStyleSheet(f"color: {_DIM}; font-size: 11px; padding: 2px;")
        slider_tip.setWordWrap(True)
        tools_box.layout().addWidget(slider_tip)

        lay.addWidget(tools_box)

        # Bottom navigation/shortcut key tips
        nav_tip = QLabel(tr("river_nav_tip"))
        nav_tip.setStyleSheet(f"color: {_DIM}; font-size: 11px; padding: 4px 2px;")
        nav_tip.setWordWrap(True)
        lay.addWidget(nav_tip)

        lay.addStretch()

    def _on_width_clicked(self, idx: int) -> None:
        """Width button selected → Uncheck Mark Group."""
        checked = self._marker_group.checkedButton()
        if checked:
            self._marker_group.setExclusive(False)
            checked.setChecked(False)
            self._marker_group.setExclusive(True)
        self.river_type_changed.emit(idx)

    def _on_marker_clicked(self, idx: int) -> None:
        """Mark button selected → Uncheck Width group."""
        checked = self._width_group.checkedButton()
        if checked:
            self._width_group.setExclusive(False)
            checked.setChecked(False)
            self._width_group.setExclusive(True)
        self.river_type_changed.emit(idx)

    def _on_river_brush(self, size: int) -> None:
        self._river_brush_label.setText(tr("river_eraser_label_fmt").format(size))
        self.brush_size_changed.emit(size)

    def showEvent(self, event):
        """Reset to default width brush (not source) every time you switch to river tab."""
        super().showEvent(event)
        if self._river_brush_slider.value() != 1:
            self._river_brush_slider.setValue(1)
        else:
            # setValue does not send a signal when the value has not changed → manual synchronization, otherwise the brush size of other modes will remain on the canvas
            self.brush_size_changed.emit(1)
        # Reset to width mode, unmark group
        default_btn = self._width_group.button(RIVER_WIDTH_4)
        if default_btn and not default_btn.isChecked():
            default_btn.setChecked(True)
            self._on_width_clicked(RIVER_WIDTH_4)


def _make_river_btn(name: str, r: int, g: int, b: int) -> QPushButton:
    """Create river type button (selected with white box)"""
    btn = QPushButton(name)
    brightness = r * 0.299 + g * 0.587 + b * 0.114
    fg = "#000000" if brightness > 140 else "#ffffff"
    btn.setStyleSheet(f"""
        QPushButton {{
            background: rgb({r},{g},{b});
            border: 2px solid transparent;
            color: {fg};
            padding: 6px 2px;
            font-size: 12px;
            font-weight: 600;
            border-radius: 4px;
            min-width: 55px;
            min-height: 28px;
        }}
        QPushButton:hover {{
            border-color: rgba(255, 255, 255, 0.5);
        }}
        QPushButton:checked {{
            border: 2px solid white;
        }}
    """)
    return btn
