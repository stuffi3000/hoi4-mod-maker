"""Map configuration (default.map) dialog.

Editable fields:
- Tree palette index (trees.bmp which palette ID counts as tree)
- Maximum river width class
- (Automatic number of provinces)"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton,
    QFormLayout, QListWidget, QListWidgetItem, QInputDialog, QMessageBox,
)

from domain.managers.default_map_settings import DefaultMapSettings
from ui.i18n import tr


class DefaultMapDialog(QDialog):
    """Map configuration editor."""

    def __init__(
        self,
        settings: DefaultMapSettings,
        province_count: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._province_count = province_count
        self.setWindowTitle(tr("dm_dlg_title"))
        self.setMinimumSize(380, 420)

        self._build_ui()
        self._refresh_tree_list()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        tip = QLabel(tr("dm_dlg_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(tip)

        form = QFormLayout()
        form.setSpacing(8)

        # Number of provinces (read only)
        prov_lbl = QLabel(tr("dm_dlg_prov_count_fmt", self._province_count))
        form.addRow(tr("dm_dlg_prov_count_label"), prov_lbl)

        # river maximum level
        self._river_max = QSpinBox()
        self._river_max.setRange(1, 10)
        self._river_max.setValue(self._settings.river_max_level)
        form.addRow(tr("dm_dlg_river_max_label"), self._river_max)

        root.addLayout(form)

        # Tree palette index (list + add/delete)
        tree_lbl = QLabel(f"<b>{tr('dm_dlg_tree_label')}</b> {tr('dm_dlg_tree_desc')}")
        tree_lbl.setStyleSheet("color: #ccc;")
        root.addWidget(tree_lbl)

        self._tree_list = QListWidget()
        self._tree_list.setMaximumHeight(140)
        root.addWidget(self._tree_list)

        tree_btn_row = QHBoxLayout()
        add_btn = QPushButton(tr("dm_dlg_add_index"))
        add_btn.clicked.connect(self._on_add_tree_index)
        del_btn = QPushButton(tr("dm_dlg_delete_selected"))
        del_btn.clicked.connect(self._on_del_tree_index)
        reset_btn = QPushButton(tr("dm_dlg_reset_default"))
        reset_btn.clicked.connect(self._on_reset_tree_indices)
        tree_btn_row.addWidget(add_btn)
        tree_btn_row.addWidget(del_btn)
        tree_btn_row.addWidget(reset_btn)
        tree_btn_row.addStretch(1)
        root.addLayout(tree_btn_row)

        root.addStretch(1)

        # bottom button
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton(tr("dm_dlg_save"))
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton(tr("dm_dlg_cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def _refresh_tree_list(self) -> None:
        self._tree_list.clear()
        for idx in self._settings.tree_palette_indices:
            self._tree_list.addItem(QListWidgetItem(str(idx)))

    def _on_add_tree_index(self) -> None:
        v, ok = QInputDialog.getInt(
            self, tr("dm_dlg_add_title"), tr("dm_dlg_add_prompt"),
            value=4, min=1, max=13,
        )
        if ok and v not in self._settings.tree_palette_indices:
            self._settings.tree_palette_indices.append(v)
            self._settings.tree_palette_indices.sort()
            self._refresh_tree_list()

    def _on_del_tree_index(self) -> None:
        row = self._tree_list.currentRow()
        if 0 <= row < len(self._settings.tree_palette_indices):
            self._settings.tree_palette_indices.pop(row)
            self._refresh_tree_list()

    def _on_reset_tree_indices(self) -> None:
        self._settings.tree_palette_indices = [3, 4, 7, 10]
        self._refresh_tree_list()

    def _on_accept(self) -> None:
        self._settings.river_max_level = int(self._river_max.value())
        self.accept()
