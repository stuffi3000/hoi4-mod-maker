"""Adjacency editor dialog.

Non-modal, user flow:
1. Open the dialog box → list shows existing adjacencies
2. Click "New" and fill in the starting point/end point/type
3. Click "Pick starting province" → enter pick mode, click on the intercept canvas in the main window to fill in the province ID
4. Click "Pick up the destination province" again → intercept for the second time
5. Click "Save" to add to the list

The main window uses the `pick_mode_changed` signal to switch the canvas interception, and uses the `province_picked` callback to fill in the fields."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QComboBox, QMessageBox,
    QGroupBox, QFormLayout,
)

import numpy as np

from domain.managers.adjacency import AdjacencyManager, AdjacencyEntry
from ui.i18n import tr


def _auto_strait_params(
    from_id: int, to_id: int,
    province_map: np.ndarray, tile_map: np.ndarray,
) -> tuple[int, int, int, int, int, int]:
    """Automatically calculate start/stop coordinates of straits and through provinces.

    Return (start_x, start_y, stop_x, stop_y, through_id, hoi4_start_y).
    The coordinates are HOI4 coordinate system (x=pixel_x, y=MAP_HEIGHT - pixel_y)."""
    from data.constants import TILE_SEA, TILE_LAKE
    h, w = province_map.shape

    # Find the boundary pixels between two provinces
    from_ys, from_xs = np.where(province_map == from_id)
    to_ys, to_xs = np.where(province_map == to_id)
    if len(from_ys) == 0 or len(to_ys) == 0:
        return -1, -1, -1, -1, -1, -1

    # Center of mass of two provinces
    from_cy, from_cx = int(from_ys.mean()), int(from_xs.mean())
    to_cy, to_cx = int(to_ys.mean()), int(to_xs.mean())

    # from saves the pixel closest to the centroid of to
    dist_from = (from_xs - to_cx) ** 2 + (from_ys - to_cy) ** 2
    best_from = int(np.argmin(dist_from))
    sx, sy = int(from_xs[best_from]), int(from_ys[best_from])

    # to saves the pixel closest to the centroid of from
    dist_to = (to_xs - from_cx) ** 2 + (to_ys - from_cy) ** 2
    best_to = int(np.argmin(dist_to))
    ex, ey = int(to_xs[best_to]), int(to_ys[best_to])

    # Find the sea province (through) on the middle line segment
    through_id = -1
    mid_x, mid_y = (sx + ex) // 2, (sy + ey) // 2
    # Search sea provinces 5x5 near midpoint
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            ny, nx = mid_y + dy, mid_x + dx
            if 0 <= ny < h and 0 <= nx < w:
                t = int(tile_map[ny, nx])
                if t in (TILE_SEA, TILE_LAKE):
                    through_id = int(province_map[ny, nx])
                    if through_id > 0:
                        break
        if through_id > 0:
            break

    # Convert to HOI4 coordinate system (y flip)
    return sx, h - sy, ex, h - ey, through_id, through_id


class AdjacencyDialog(QDialog):

    changed = pyqtSignal()
    """Editor for province adjacency rules.

    ``pick_mode_changed`` carries ``(enabled, target_field)``. The main window
    intercepts the next canvas click and sends it to the picker callback.
    """

    pick_mode_changed = pyqtSignal(bool, str)

    def __init__(self, adjacency_mgr: AdjacencyManager, parent=None,
                 province_map: np.ndarray | None = None,
                 tile_map: np.ndarray | None = None) -> None:
        super().__init__(parent)
        self._mgr = adjacency_mgr
        self._province_map = province_map
        self._tile_map = tile_map
        self._pick_target: str | None = None  # 'from' / 'to' / 'through'
        self.setWindowTitle(tr("adj_dlg_title"))
        self.setMinimumSize(400, 520)
        self.setWindowFlags(self.windowFlags() | Qt.Tool)

        self._build_ui()
        self._refresh_list()

    # ─────────── UI ───────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        tip = QLabel(tr("adj_dlg_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(tip)

        # list
        self._list = QListWidget()
        self._list.setMaximumHeight(150)
        self._list.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self._list)

        del_btn = QPushButton(tr("adj_dlg_delete_selected"))
        del_btn.clicked.connect(self._on_delete)
        root.addWidget(del_btn)

        # Editing area
        edit_box = QGroupBox(tr("adj_dlg_edit_group"))
        form = QFormLayout(edit_box)
        form.setSpacing(6)

        # starting point
        from_row = QHBoxLayout()
        self._from_edit = QLineEdit()
        self._from_edit.setPlaceholderText(tr("adj_dlg_from_placeholder"))
        from_row.addWidget(self._from_edit)
        from_pick = QPushButton(tr("adj_dlg_pick_from_canvas"))
        from_pick.clicked.connect(lambda: self._start_pick("from"))
        from_row.addWidget(from_pick)
        form.addRow(tr("adj_dlg_from_label"), from_row)

        # end point
        to_row = QHBoxLayout()
        self._to_edit = QLineEdit()
        self._to_edit.setPlaceholderText(tr("adj_dlg_to_placeholder"))
        to_row.addWidget(self._to_edit)
        to_pick = QPushButton(tr("adj_dlg_pick_from_canvas"))
        to_pick.clicked.connect(lambda: self._start_pick("to"))
        to_row.addWidget(to_pick)
        form.addRow(tr("adj_dlg_to_label"), to_row)

        # Type
        self._type_combo = QComboBox()
        self._type_combo.addItem(tr("adj_dlg_type_sea"), "sea")
        self._type_combo.addItem(tr("adj_dlg_type_impassable"), "impassable")
        form.addRow(tr("adj_dlg_type_label"), self._type_combo)

        # through (sea only)
        through_row = QHBoxLayout()
        self._through_edit = QLineEdit()
        self._through_edit.setPlaceholderText(tr("adj_dlg_through_placeholder"))
        through_row.addWidget(self._through_edit)
        through_pick = QPushButton(tr("adj_dlg_pick_from_canvas"))
        through_pick.clicked.connect(lambda: self._start_pick("through"))
        through_row.addWidget(through_pick)
        form.addRow(tr("adj_dlg_through_label"), through_row)

        # comment
        self._comment_edit = QLineEdit()
        self._comment_edit.setPlaceholderText(tr("adj_dlg_comment_placeholder"))
        form.addRow(tr("adj_dlg_comment_label"), self._comment_edit)

        root.addWidget(edit_box)

        # Status + Save/Clear
        self._status = QLabel("")
        self._status.setStyleSheet("color: #4a9; font-size: 11px;")
        root.addWidget(self._status)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton(tr("adj_dlg_clear_fields"))
        clear_btn.clicked.connect(self._clear_form)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch(1)
        save_btn = QPushButton(tr("adj_dlg_save"))
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    # ─────────── List ────────────

    def _refresh_list(self) -> None:
        self._list.clear()
        for e in self._mgr.get_all():
            label = f"[{e.type}] {e.from_id} → {e.to_id}"
            if e.through_id >= 0:
                label += f" (via {e.through_id})"
            if e.comment:
                label += f"  # {e.comment}"
            item = QListWidgetItem(label)
            self._list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """Click on the list item → backfill it into the editing area for easy modification."""
        row = self._list.row(item)
        entries = self._mgr.get_all()
        if 0 <= row < len(entries):
            e = entries[row]
            self._from_edit.setText(str(e.from_id))
            self._to_edit.setText(str(e.to_id))
            self._through_edit.setText(str(e.through_id) if e.through_id >= 0 else "")
            idx = self._type_combo.findData(e.type)
            if idx >= 0:
                self._type_combo.setCurrentIndex(idx)
            self._comment_edit.setText(e.comment)

    def _on_delete(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        entries = self._mgr.get_all()
        if 0 <= row < len(entries):
            e = entries[row]
            self._mgr.remove(e.from_id, e.to_id, e.type)
            self._refresh_list()
            self.changed.emit()

    # ─────────── Form ────────────

    def _clear_form(self) -> None:
        self._from_edit.clear()
        self._to_edit.clear()
        self._through_edit.clear()
        self._comment_edit.clear()
        self._type_combo.setCurrentIndex(0)

    def _on_save(self) -> None:
        try:
            from_id = int(self._from_edit.text().strip())
            to_id = int(self._to_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, tr("dlg_error"), tr("adj_dlg_err_invalid_id"))
            return
        t = self._type_combo.currentData()
        through_text = self._through_edit.text().strip()
        through_id = int(through_text) if through_text else -1

        # Automatically calculate coordinates and through (sea type)
        start_x = start_y = stop_x = stop_y = -1
        if t == "sea" and self._province_map is not None and self._tile_map is not None:
            sx, sy, ex, ey, auto_through, _ = _auto_strait_params(
                from_id, to_id, self._province_map, self._tile_map
            )
            start_x, start_y, stop_x, stop_y = sx, sy, ex, ey
            if through_id <= 0 and auto_through > 0:
                through_id = auto_through
                self._through_edit.setText(str(through_id))

        entry = AdjacencyEntry(
            from_id=from_id,
            to_id=to_id,
            type=t,
            through_id=through_id if t == "sea" else -1,
            start_x=start_x, start_y=start_y,
            stop_x=stop_x, stop_y=stop_y,
            comment=self._comment_edit.text().strip(),
        )
        self._mgr.add(entry)
        self._refresh_list()
        self.changed.emit()
        coord_info = f" ({start_x},{start_y})→({stop_x},{stop_y})" if start_x >= 0 else ""
        self._status.setText(tr("adj_dlg_saved_fmt", from_id, to_id, t, coord_info))

    # ─────────── Pickup mode ────────────

    def _start_pick(self, target: str) -> None:
        """target ∈ {'from','to','through'}"""
        self._pick_target = target
        self._status.setText(tr("adj_dlg_pick_status_fmt", target))
        self.pick_mode_changed.emit(True, target)

    def receive_picked_province(self, pid: int) -> None:
        """The main window calls this method after intercepting a click on the canvas."""
        if self._pick_target == "from":
            self._from_edit.setText(str(pid))
        elif self._pick_target == "to":
            self._to_edit.setText(str(pid))
        elif self._pick_target == "through":
            self._through_edit.setText(str(pid))
        self._status.setText(tr("adj_dlg_filled_fmt", self._pick_target, pid))
        self._pick_target = None
        self.pick_mode_changed.emit(False, "")

    def closeEvent(self, event) -> None:
        if self._pick_target is not None:
            self.pick_mode_changed.emit(False, "")
            self._pick_target = None
        super().closeEvent(event)
