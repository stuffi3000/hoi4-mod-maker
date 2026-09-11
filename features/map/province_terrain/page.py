"""Province attribute terrain page — Select terrain type button + operation instructions.

Operation: Select the terrain type → click province on the canvas → the province gameplay terrain = this type.
Unmoving terrain.bmp visual, unmoving height_map height."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QButtonGroup, QCheckBox,
)

from data.terrain_types import TERRAIN_TYPES, terrain_display_name
from ui.styles import (
    make_section as _make_section,
    _DIM, _DIM_LABEL_STYLE,
)
from ui.i18n import tr


# 8 land types (excluding ocean/lakes)
_LAND_TYPES = ["plains", "forest", "hills", "mountain",
               "desert", "marsh", "jungle", "urban"]


class ProvincialTerrainPage(QWidget):
    """Province attribute terrain selection page."""

    type_changed = pyqtSignal(str)
    assign_mode_changed = pyqtSignal(bool)  # True=Assign mode (click to change terrain)/False=View mode (click to view information only)
    sync_requested = pyqtSignal()  # Fully recalculate attributes from visual terrain (secondary confirmation)
    vp_overlay_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        intro = QLabel(tr("pterrain_intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 4px;")
        intro.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(intro)

        # Distribution mode switch
        self._assign_chk = QCheckBox(tr("pterrain_assign_mode"))
        self._assign_chk.setChecked(False)  # Closed by default to avoid accidental changes
        self._assign_chk.setStyleSheet(
            f"QCheckBox {{ color: #e8eaed; font-size: 14px; font-weight: 600; padding: 6px; }}"
            f"QCheckBox:checked {{ color: #86efac; }}"  # Turns green when turned on
        )
        self._assign_chk.toggled.connect(self.assign_mode_changed)
        outer.addWidget(self._assign_chk)

        self._vp_overlay_chk = QCheckBox(tr("terrain_show_victory_points"))
        self._vp_overlay_chk.setToolTip(tr("terrain_show_victory_points_tip"))
        self._vp_overlay_chk.toggled.connect(self.vp_overlay_toggled.emit)
        outer.addWidget(self._vp_overlay_chk)

        type_box = _make_section(tr("pterrain_section_types"))
        type_layout = type_box.layout()
        grid = QGridLayout()
        grid.setSpacing(4)

        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)

        for i, tname in enumerate(_LAND_TYPES):
            terrain = TERRAIN_TYPES.get(tname)
            if terrain is None:
                continue
            r, g, b = terrain.color
            btn = QPushButton(f"{terrain_display_name(terrain)}\n({tname})")
            btn.setCheckable(True)
            btn.setMinimumHeight(50)
            btn.setStyleSheet(
                f"QPushButton {{ background: rgb({r},{g},{b}); color: #fff; "
                f"border: 1px solid #333; border-radius: 4px; padding: 4px; "
                f"font-size: 11px; font-weight: 500; }} "
                f"QPushButton:checked {{ border: 2px solid #fff; }}"
            )
            btn.setProperty("type_name", tname)
            self._btn_group.addButton(btn, i)
            grid.addWidget(btn, i // 2, i % 2)

        type_layout.addLayout(grid)
        outer.addWidget(type_box)

        first = self._btn_group.button(0)
        if first:
            first.setChecked(True)

        self._btn_group.buttonClicked.connect(self._on_type_clicked)

        plains_name = terrain_display_name(TERRAIN_TYPES["plains"]) if "plains" in TERRAIN_TYPES else "plains"
        self._status_label = QLabel(tr("pterrain_current_label", plains_name, "plains"))
        self._status_label.setStyleSheet(_DIM_LABEL_STYLE)
        outer.addWidget(self._status_label)

        # Resync from visual terrain (full attribute override, reversible)
        sync_box = _make_section(tr("pterrain_sync_section"))
        sync_layout = sync_box.layout()
        self._sync_btn = QPushButton(tr("pterrain_sync_btn"))
        self._sync_btn.setMinimumHeight(36)
        self._sync_btn.setToolTip(tr("pterrain_sync_hint"))
        self._sync_btn.clicked.connect(self._on_sync_clicked)
        sync_layout.addWidget(self._sync_btn)
        sync_hint = QLabel(tr("pterrain_sync_hint"))
        sync_hint.setWordWrap(True)
        sync_hint.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        sync_layout.addWidget(sync_hint)
        outer.addWidget(sync_box)

        outer.addStretch()

    def _on_sync_clicked(self) -> None:
        """Fool-proof: double confirmation (covering all province attributes, can only be restored by revoking)."""
        from PyQt5.QtWidgets import QMessageBox
        ret = QMessageBox.question(
            self, tr("pterrain_sync_confirm_title"),
            tr("pterrain_sync_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self.sync_requested.emit()

    def _on_type_clicked(self, btn: QPushButton) -> None:
        tname = btn.property("type_name")
        if tname:
            terrain = TERRAIN_TYPES.get(tname)
            name = terrain_display_name(terrain) if terrain else tname
            self._status_label.setText(tr("pterrain_current_label", name, tname))
            self.type_changed.emit(tname)

    def current_type(self) -> str:
        btn = self._btn_group.checkedButton()
        if btn is None:
            return "plains"
        return btn.property("type_name") or "plains"
