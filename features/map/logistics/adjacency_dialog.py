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
from domain.managers.adjacency_rule import AdjacencyRuleManager
from commands.map.logistics_edit import AdjacencyReviewCommand, apply_manager_edit
from domain.adjacency_review import (
    adjacency_layer_count,
    adjacency_layer_hash,
    normalize_review_state,
)
from services.adjacency_io import adjacency_geometry
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
                 tile_map: np.ndarray | None = None,
                 history=None, project=None,
                 rule_mgr: AdjacencyRuleManager | None = None) -> None:
        super().__init__(parent)
        self._mgr = adjacency_mgr
        self._province_map = province_map
        self._tile_map = tile_map
        self._history = history
        self._project = project
        self._rule_mgr = rule_mgr
        self._pick_target: str | None = None  # 'from' / 'to' / 'through'
        self._editing_key: tuple[int, int, str] | None = None
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

        review_box = QGroupBox(tr("adj_dlg_review_group"))
        review_layout = QVBoxLayout(review_box)
        self._review_status = QLabel()
        self._review_status.setWordWrap(True)
        self._review_status.setStyleSheet("color: #9aa0ab; font-size: 11px;")
        review_layout.addWidget(self._review_status)
        self._review_button = QPushButton()
        self._review_button.clicked.connect(self._on_adjacency_review_clicked)
        review_layout.addWidget(self._review_button)
        root.addWidget(review_box)

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

        # Explicit geometry is part of the import/export contract.  Empty
        # values remain -1, while a completely empty sea geometry can still
        # be inferred from the map when saving.
        geometry_row = QHBoxLayout()
        self._start_x_edit = QLineEdit()
        self._start_y_edit = QLineEdit()
        self._stop_x_edit = QLineEdit()
        self._stop_y_edit = QLineEdit()
        for edit in (self._start_x_edit, self._start_y_edit,
                     self._stop_x_edit, self._stop_y_edit):
            edit.setPlaceholderText("-1")
            geometry_row.addWidget(edit)
        form.addRow(tr("adj_dlg_geometry_label"), geometry_row)

        self._rule_edit = QLineEdit()
        self._rule_edit.setPlaceholderText(tr("adj_dlg_rule_placeholder"))
        form.addRow(tr("adj_dlg_rule_label"), self._rule_edit)

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
        known_provinces = (
            set(int(pid) for pid in np.unique(self._province_map))
            if self._province_map is not None else None
        )
        for e in self._mgr.get_all():
            label = f"[{e.type}] {e.from_id} → {e.to_id}"
            if e.through_id >= 0:
                label += f" (via {e.through_id})"
            if e.comment:
                label += f"  # {e.comment}"
            if e.rule_name:
                label += f"  [{e.rule_name}]"
                rule = self._rule_mgr.get(e.rule_name) if self._rule_mgr is not None else None
                if rule is None:
                    label += " ⚠ missing rule"
                elif rule.required_provinces:
                    required = ",".join(str(pid) for pid in rule.required_provinces)
                    label += f"  requires {required}"
            width = self._province_map.shape[1] if self._province_map is not None else None
            geometry = adjacency_geometry(
                e,
                width,
                self._province_map.shape[0] if self._province_map is not None else None,
            )
            if geometry["wrap_horizontal"]:
                label += "  ↔ wrap"
            if geometry["in_bounds"] is False:
                label += "  ⚠ invalid geometry"
            invalid = self._invalid_province_references(e, known_provinces)
            if invalid:
                label += "  ⚠ invalid " + ",".join(str(pid) for pid in invalid)
            item = QListWidgetItem(label)
            self._list.addItem(item)
        self._refresh_review_controls()

    def _refresh_review_controls(self) -> None:
        """Show the explicit empty-layer review choice next to the editor."""
        meta = getattr(self._project, "project_meta", None)
        if meta is None:
            self._review_status.setText(tr("adj_dlg_review_unavailable"))
            self._review_button.setEnabled(False)
            return

        state = normalize_review_state(getattr(meta, "adjacency_review", "unreviewed"))
        count = adjacency_layer_count(self._mgr, self._rule_mgr)
        if state == "none_intended":
            self._review_status.setText(tr("adj_dlg_none_status"))
            self._review_button.setText(tr("adj_dlg_reopen_review"))
        else:
            self._review_status.setText(
                tr("adj_dlg_review_status_fmt").format(state=state, count=count)
            )
            self._review_button.setText(tr("adj_dlg_mark_none"))
        self._review_button.setEnabled(True)

    def _on_adjacency_review_clicked(self) -> None:
        """Mark an empty adjacency layer as intentional, or reopen review."""
        meta = getattr(self._project, "project_meta", None)
        if meta is None:
            return
        current = normalize_review_state(getattr(meta, "adjacency_review", "unreviewed"))
        if current == "none_intended":
            after = ("unreviewed", "", None)
        else:
            count = adjacency_layer_count(self._mgr, self._rule_mgr)
            if count:
                QMessageBox.warning(
                    self,
                    tr("dlg_error"),
                    tr("adj_dlg_none_requires_empty").format(count=count),
                )
                return
            after = (
                "none_intended",
                tr("adj_dlg_none_note"),
                adjacency_layer_hash(self._mgr, self._rule_mgr),
            )

        before = (
            str(getattr(meta, "adjacency_review", "unreviewed")),
            str(getattr(meta, "adjacency_review_note", "") or ""),
            getattr(meta, "adjacency_review_hash", None),
        )
        if before == after:
            return
        command = AdjacencyReviewCommand(self._project, before, after)
        if self._history is not None:
            self._history.execute(command)
        else:
            command.execute()
        self._refresh_review_controls()
        self.changed.emit()
        self._status.setText(
            tr("adj_dlg_none_selected")
            if after[0] == "none_intended"
            else tr("adj_dlg_review_reopened")
        )

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """Click on the list item → backfill it into the editing area for easy modification."""
        row = self._list.row(item)
        entries = self._mgr.get_all()
        if 0 <= row < len(entries):
            e = entries[row]
            self._editing_key = (e.from_id, e.to_id, e.type)
            self._from_edit.setText(str(e.from_id))
            self._to_edit.setText(str(e.to_id))
            self._through_edit.setText(str(e.through_id) if e.through_id >= 0 else "")
            self._start_x_edit.setText(str(e.start_x) if e.start_x >= 0 else "")
            self._start_y_edit.setText(str(e.start_y) if e.start_y >= 0 else "")
            self._stop_x_edit.setText(str(e.stop_x) if e.stop_x >= 0 else "")
            self._stop_y_edit.setText(str(e.stop_y) if e.stop_y >= 0 else "")
            self._rule_edit.setText(e.rule_name)
            idx = self._type_combo.findData(e.type)
            if idx >= 0:
                self._type_combo.setCurrentIndex(idx)
            self._comment_edit.setText(e.comment)

    def _invalid_province_references(
        self,
        entry: AdjacencyEntry,
        known_provinces: set[int] | None = None,
    ) -> list[int]:
        if known_provinces is None:
            return []
        references = [entry.from_id, entry.to_id]
        if entry.through_id >= 0:
            references.append(entry.through_id)
        if self._rule_mgr is not None and entry.rule_name:
            rule = self._rule_mgr.get(entry.rule_name)
            if rule is not None:
                references.extend(rule.required_provinces)
        return sorted({pid for pid in references if pid > 0 and pid not in known_provinces})

    def _on_delete(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        entries = self._mgr.get_all()
        if 0 <= row < len(entries):
            e = entries[row]
            if self._apply_edit(
                tr("adj_dlg_delete_command"),
                lambda manager: manager.remove(e.from_id, e.to_id, e.type),
            ):
                self._editing_key = None
                self._refresh_list()
                self.changed.emit()

    # ─────────── Form ────────────

    def _clear_form(self) -> None:
        self._from_edit.clear()
        self._to_edit.clear()
        self._through_edit.clear()
        for edit in (self._start_x_edit, self._start_y_edit,
                     self._stop_x_edit, self._stop_y_edit):
            edit.clear()
        self._rule_edit.clear()
        self._comment_edit.clear()
        self._type_combo.setCurrentIndex(0)
        self._editing_key = None

    def _on_save(self) -> None:
        try:
            from_id = int(self._from_edit.text().strip())
            to_id = int(self._to_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, tr("dlg_error"), tr("adj_dlg_err_invalid_id"))
            return
        if from_id <= 0 or to_id <= 0 or from_id == to_id:
            QMessageBox.warning(self, tr("dlg_error"), tr("adj_dlg_err_invalid_id"))
            return
        t = self._type_combo.currentData()
        through_text = self._through_edit.text().strip()
        try:
            through_id = int(through_text) if through_text else -1
            coordinates = [
                int(edit.text().strip()) if edit.text().strip() else -1
                for edit in (
                    self._start_x_edit, self._start_y_edit,
                    self._stop_x_edit, self._stop_y_edit,
                )
            ]
        except ValueError:
            QMessageBox.warning(self, tr("dlg_error"), tr("adj_dlg_err_invalid_geometry"))
            return

        # Automatically calculate coordinates and through (sea type)
        start_x, start_y, stop_x, stop_y = coordinates
        if (
            t == "sea"
            and all(value < 0 for value in coordinates)
            and self._province_map is not None
            and self._tile_map is not None
        ):
            sx, sy, ex, ey, auto_through, _ = _auto_strait_params(
                from_id, to_id, self._province_map, self._tile_map
            )
            start_x, start_y, stop_x, stop_y = sx, sy, ex, ey
            coordinates = [start_x, start_y, stop_x, stop_y]
            if through_id <= 0 and auto_through > 0:
                through_id = auto_through
                self._through_edit.setText(str(through_id))

        if t == "impassable":
            through_id = -1
            start_x = start_y = stop_x = stop_y = -1

        rule_name = self._rule_edit.text().strip() if t == "sea" else ""

        entry = AdjacencyEntry(
            from_id=from_id,
            to_id=to_id,
            type=t,
            through_id=through_id if t == "sea" else -1,
            start_x=start_x, start_y=start_y,
            stop_x=stop_x, stop_y=stop_y,
            rule_name=rule_name,
            comment=self._comment_edit.text().strip(),
        )

        editing_key = self._editing_key

        def mutate(manager) -> None:
            if editing_key is not None:
                manager.remove(*editing_key)
            manager.add(entry)

        if not self._apply_edit(tr("adj_dlg_save_command"), mutate):
            return
        self._editing_key = (entry.from_id, entry.to_id, entry.type)
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

    def _apply_edit(self, label: str, mutate) -> bool:
        return apply_manager_edit(
            self._mgr,
            label,
            mutate,
            history=self._history,
            project=self._project,
            invalidate_adjacency_review=True,
        )

    def closeEvent(self, event) -> None:
        if self._pick_target is not None:
            self.pick_mode_changed.emit(False, "")
            self._pick_target = None
        super().closeEvent(event)
