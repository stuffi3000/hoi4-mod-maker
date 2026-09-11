"""Strategy overview map color dialog.

3 color block buttons (land/sea/lake), click to pop up QColorDialog. Real-time preview.
Save to ColormapSettings and use these colors next time you export colormap_dds.dds."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QColorDialog,
    QGroupBox,
)

from domain.managers.colormap_settings import ColormapSettings, ColormapColor
from ui.i18n import tr


class ColormapDialog(QDialog):
    """Strategy overview map color editor."""

    def __init__(self, settings: ColormapSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle(tr("cm_dlg_title"))
        self.setMinimumSize(360, 360)

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        tip = QLabel(tr("cm_dlg_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(tip)

        # rows of three color blocks
        self._land_swatch = self._make_color_row(
            root, tr("cm_dlg_land"), self._settings.land, self._on_pick_land
        )
        self._sea_swatch = self._make_color_row(
            root, tr("cm_dlg_sea"), self._settings.sea, self._on_pick_sea
        )
        self._lake_swatch = self._make_color_row(
            root, tr("cm_dlg_lake"), self._settings.lake, self._on_pick_lake
        )

        # reset button
        reset_btn = QPushButton(tr("cm_dlg_reset_default"))
        reset_btn.clicked.connect(self._on_reset)
        root.addWidget(reset_btn)

        root.addStretch(1)

        # bottom button
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton(tr("cm_dlg_save"))
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(tr("cm_dlg_cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def _make_color_row(
        self, parent_layout, label_text: str, color: ColormapColor, on_click
    ) -> QPushButton:
        row = QHBoxLayout()
        lbl = QLabel(f"{label_text}:")
        lbl.setMinimumWidth(60)
        row.addWidget(lbl)

        swatch = QPushButton()
        swatch.setFixedSize(140, 32)
        swatch.clicked.connect(on_click)
        row.addWidget(swatch)
        row.addStretch(1)
        self._update_swatch(swatch, color)
        parent_layout.addLayout(row)
        return swatch

    def _update_swatch(self, swatch: QPushButton, color: ColormapColor) -> None:
        swatch.setStyleSheet(
            f"background-color: rgb({color.r}, {color.g}, {color.b});"
            f" border: 1px solid #2a3a55;"
        )
        swatch.setText(f"({color.r}, {color.g}, {color.b})")

    def _pick_color(self, current: ColormapColor) -> ColormapColor | None:
        qc = QColor(current.r, current.g, current.b)
        new_qc = QColorDialog.getColor(qc, self, tr("cm_dlg_pick_color"))
        if new_qc.isValid():
            return ColormapColor(new_qc.red(), new_qc.green(), new_qc.blue())
        return None

    def _on_pick_land(self) -> None:
        c = self._pick_color(self._settings.land)
        if c:
            self._settings.land = c
            self._update_swatch(self._land_swatch, c)

    def _on_pick_sea(self) -> None:
        c = self._pick_color(self._settings.sea)
        if c:
            self._settings.sea = c
            self._update_swatch(self._sea_swatch, c)

    def _on_pick_lake(self) -> None:
        c = self._pick_color(self._settings.lake)
        if c:
            self._settings.lake = c
            self._update_swatch(self._lake_swatch, c)

    def _on_reset(self) -> None:
        defaults = ColormapSettings.default()
        self._settings.land = defaults.land
        self._settings.sea = defaults.sea
        self._settings.lake = defaults.lake
        self._update_swatch(self._land_swatch, self._settings.land)
        self._update_swatch(self._sea_swatch, self._settings.sea)
        self._update_swatch(self._lake_swatch, self._settings.lake)
