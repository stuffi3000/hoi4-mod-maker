"""Continent Editor Dialog — Add, delete, or modify continent names, and assign provinces to the selected continent.

Usage: Open the dialog box → select a continent → enter "pickup mode" → click on the province on the main canvas
(The main window intercepts the click event and calls continent_mgr.assign_province)"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QInputDialog, QMessageBox,
)

from ui.i18n import tr


class ContinentDialog(QDialog):
    """Non-modal, allowing users to click provinces and assign continents while looking at the canvas."""

    # The user enters/exits picking mode; the main window is used to toggle canvas click behavior
    pick_mode_changed = pyqtSignal(bool, int)  # (on/off, mainland index 0-based)

    def __init__(self, continent_mgr, parent=None):
        super().__init__(parent)
        self._mgr = continent_mgr
        self._pick_on = False
        self.setWindowTitle(tr("cont_dlg_title"))
        self.setMinimumSize(340, 420)
        # Non-modal: Does not block main window clicks
        self.setWindowFlags(self.windowFlags() | Qt.Tool)

        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        tip = QLabel(tr("cont_dlg_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888; font-size: 11px;")
        lay.addWidget(tip)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_rename)
        lay.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton(tr("cont_dlg_add"))
        add_btn.clicked.connect(self._on_add)
        rename_btn = QPushButton(tr("cont_dlg_rename"))
        rename_btn.clicked.connect(self._on_rename)
        remove_btn = QPushButton(tr("cont_dlg_delete"))
        remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rename_btn)
        btn_row.addWidget(remove_btn)
        lay.addLayout(btn_row)

        self._pick_btn = QPushButton(tr("cont_dlg_start_assign"))
        self._pick_btn.setCheckable(True)
        self._pick_btn.toggled.connect(self._on_pick_toggled)
        lay.addWidget(self._pick_btn)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #4a9; font-size: 11px;")
        lay.addWidget(self._status)

    def _refresh_list(self) -> None:
        self._list.clear()
        for i, name in enumerate(self._mgr.names):
            count = sum(
                1 for ci in self._mgr._province_continent.values() if ci == i
            )
            item = QListWidgetItem(f"{i + 1}. {name}  ({tr('cont_dlg_list_item_fmt', count)})")
            item.setData(Qt.UserRole, i)
            self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def current_index(self) -> int:
        """Returns the currently selected continent index (0-based), or -1 if no selection is made."""
        item = self._list.currentItem()
        if item is None:
            return -1
        return int(item.data(Qt.UserRole))

    # ─────────── Mainland CRUD ───────────

    def _on_add(self) -> None:
        name, ok = QInputDialog.getText(self, tr("cont_dlg_add_title"), tr("cont_dlg_add_prompt"))
        if not ok or not name.strip():
            return
        try:
            self._mgr.add_continent(name.strip())
        except ValueError as e:
            QMessageBox.warning(self, tr("dlg_error"), str(e))
            return
        self._refresh_list()

    def _on_rename(self) -> None:
        idx = self.current_index()
        if idx < 0:
            return
        old = self._mgr.get_name(idx)
        name, ok = QInputDialog.getText(
            self, tr("cont_dlg_rename_title"), tr("cont_dlg_rename_prompt"), text=old
        )
        if not ok or not name.strip():
            return
        try:
            self._mgr.rename_continent(idx, name.strip())
        except (ValueError, IndexError) as e:
            QMessageBox.warning(self, tr("dlg_error"), str(e))
            return
        self._refresh_list()

    def _on_remove(self) -> None:
        idx = self.current_index()
        if idx < 0:
            return
        if self._mgr.count() <= 1:
            QMessageBox.warning(self, tr("dlg_error"), tr("cont_dlg_err_min_one"))
            return
        name = self._mgr.get_name(idx)
        ret = QMessageBox.question(
            self, tr("cont_dlg_delete_title"),
            tr("cont_dlg_delete_confirm_fmt", name),
        )
        if ret != QMessageBox.Yes:
            return
        try:
            self._mgr.remove_continent(idx)
        except (ValueError, IndexError) as e:
            QMessageBox.warning(self, tr("dlg_error"), str(e))
            return
        self._refresh_list()

    # ─────────── Pickup mode ────────────

    def _on_pick_toggled(self, on: bool) -> None:
        idx = self.current_index()
        if on and idx < 0:
            self._pick_btn.setChecked(False)
            QMessageBox.warning(self, tr("dlg_error"), tr("cont_dlg_err_select"))
            return
        self._pick_on = on
        if on:
            self._pick_btn.setText(tr("cont_dlg_stop_assign"))
            name = self._mgr.get_name(idx)
            self._status.setText(tr("cont_dlg_assigning_fmt", name))
        else:
            self._pick_btn.setText(tr("cont_dlg_start_assign"))
            self._status.setText("")
        self.pick_mode_changed.emit(on, idx)

    def notify_assigned(self, pid: int) -> None:
        """Called after assigning a province in the main window, the province number display is refreshed."""
        self._refresh_list()
        idx = self.current_index()
        if 0 <= idx:
            name = self._mgr.get_name(idx)
            self._status.setText(tr("cont_dlg_assigned_fmt", pid, name))

    def closeEvent(self, event) -> None:
        # Automatically exit pickup mode when closed
        if self._pick_on:
            self.pick_mode_changed.emit(False, -1)
            self._pick_on = False
        super().closeEvent(event)
