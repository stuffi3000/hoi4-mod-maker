"""
战略区域编辑器对话框.

非模态. 用法:
1. 打开对话框 → 左侧 region 列表
2. "自动生成" 按钮 → 按 state 分组, weather 按纬度
3. 选 region → 右侧编辑: 名字 / weather 预设 / naval_terrain
4. "拾取模式" → 点画布上的省份 → 加入/移出当前 region

复用 continent dialog 的 pick_mode_changed 模式.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QComboBox,
    QGroupBox, QMessageBox,
)

from domain.managers.strategic_region import (
    StrategicRegionManager, StrategicRegion, PRESET_LABELS,
    weather_preset_display_name,
)
from ui.i18n import tr


class StrategicRegionDialog(QDialog):
    """战略区域编辑器. 非模态, 支持画布拾取省份."""

    pick_mode_changed = pyqtSignal(bool, int)  # (开/关, region_id)

    def __init__(
        self,
        region_mgr: StrategicRegionManager,
        state_mgr=None,
        province_map=None,
        tile_map=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._mgr = region_mgr
        self._state_mgr = state_mgr
        self._province_map = province_map
        self._tile_map = tile_map
        self._pick_on = False
        self.setWindowTitle(tr("sr_dlg_title"))
        self.setMinimumSize(540, 520)
        self.setWindowFlags(self.windowFlags() | Qt.Tool)

        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ── 左: 列表 ──
        left = QVBoxLayout()
        left_lbl = QLabel(f"<b>{tr('sr_dlg_region_list')}</b>")
        left.addWidget(left_lbl)
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_select)
        left.addWidget(self._list, 1)

        auto_btn = QPushButton(tr("sr_dlg_auto_generate"))
        auto_btn.clicked.connect(self._on_auto_generate)
        left.addWidget(auto_btn)

        new_btn = QPushButton(tr("sr_dlg_new_region"))
        new_btn.clicked.connect(self._on_new)
        left.addWidget(new_btn)

        del_btn = QPushButton(tr("sr_dlg_delete_selected"))
        del_btn.clicked.connect(self._on_delete)
        left.addWidget(del_btn)

        root.addLayout(left, 1)

        # ── 右: 详情 ──
        right = QVBoxLayout()

        # 名字
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(tr("sr_dlg_name_label")))
        self._name_edit = QLineEdit()
        self._name_edit.editingFinished.connect(self._on_name_changed)
        name_row.addWidget(self._name_edit)
        right.addLayout(name_row)

        # weather 预设
        weather_row = QHBoxLayout()
        weather_row.addWidget(QLabel(tr("sr_dlg_weather_label")))
        self._weather_combo = QComboBox()
        for key in PRESET_LABELS:
            self._weather_combo.addItem(weather_preset_display_name(key), key)
        self._weather_combo.currentIndexChanged.connect(self._on_weather_changed)
        weather_row.addWidget(self._weather_combo)
        right.addLayout(weather_row)

        # naval_terrain
        naval_row = QHBoxLayout()
        naval_row.addWidget(QLabel("Naval terrain:"))
        self._naval_combo = QComboBox()
        self._naval_combo.addItem(tr("sr_dlg_naval_none"), "")
        for value, label_key in (
            ("water_deep_ocean", "sr_naval_deep_ocean"),
            ("water_shallow_sea", "sr_naval_shallow_sea"),
            ("water_fjords", "sr_naval_fjords"),
        ):
            self._naval_combo.addItem(tr(label_key), value)
        self._naval_combo.currentIndexChanged.connect(self._on_naval_changed)
        naval_row.addWidget(self._naval_combo)
        right.addLayout(naval_row)

        # 省份数
        self._prov_count_label = QLabel(tr("sr_dlg_province_count"))
        right.addWidget(self._prov_count_label)

        # 拾取按钮
        self._pick_btn = QPushButton(tr("sr_dlg_start_pick"))
        self._pick_btn.setCheckable(True)
        self._pick_btn.toggled.connect(self._on_pick_toggled)
        right.addWidget(self._pick_btn)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #4a9; font-size: 11px;")
        right.addWidget(self._status)

        right.addStretch(1)

        close_btn = QPushButton(tr("sr_dlg_close"))
        close_btn.clicked.connect(self.accept)
        right.addWidget(close_btn)

        root.addLayout(right, 2)

    # ─────────── 列表 ───────────

    def _refresh_list(self) -> None:
        self._list.clear()
        for r in sorted(self._mgr.regions.values(), key=lambda x: x.id):
            label = f"#{r.id} {r.name}  ({tr('sr_dlg_list_item_fmt', len(r.province_ids))}, {weather_preset_display_name(r.weather_preset)})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r.id)
            self._list.addItem(item)

    def _current_rid(self) -> int:
        item = self._list.currentItem()
        return int(item.data(Qt.UserRole)) if item else 0

    def _on_select(self, item: QListWidgetItem) -> None:
        rid = int(item.data(Qt.UserRole))
        r = self._mgr.get(rid)
        if r is None:
            return
        self._name_edit.blockSignals(True)
        self._name_edit.setText(r.name)
        self._name_edit.blockSignals(False)
        idx = self._weather_combo.findData(r.weather_preset)
        if idx >= 0:
            self._weather_combo.blockSignals(True)
            self._weather_combo.setCurrentIndex(idx)
            self._weather_combo.blockSignals(False)
        nidx = self._naval_combo.findData(r.naval_terrain or "")
        if nidx >= 0:
            self._naval_combo.blockSignals(True)
            self._naval_combo.setCurrentIndex(nidx)
            self._naval_combo.blockSignals(False)
        self._prov_count_label.setText(tr("sr_dlg_province_count_fmt", len(r.province_ids)))

    # ─────────── 操作 ───────────

    def _on_auto_generate(self) -> None:
        if self._province_map is None or self._tile_map is None:
            QMessageBox.warning(self, tr("dlg_error"), tr("sr_dlg_err_no_provinces"))
            return
        ret = QMessageBox.question(
            self, tr("dlg_auto_generate"),
            tr("sr_dlg_auto_confirm"),
        )
        if ret != QMessageBox.Yes:
            return
        self._mgr.auto_generate(
            self._province_map, self._tile_map,
            state_mgr=self._state_mgr,
        )
        self._refresh_list()
        self._status.setText(tr("sr_dlg_generated_fmt", self._mgr.count()))

    def _on_new(self) -> None:
        r = self._mgr.create_region()
        self._refresh_list()
        # 选中新的
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.UserRole) == r.id:
                self._list.setCurrentRow(i)
                self._on_select(self._list.item(i))
                break

    def _on_delete(self) -> None:
        rid = self._current_rid()
        if rid <= 0:
            return
        self._mgr.remove_region(rid)
        self._refresh_list()

    def _on_name_changed(self) -> None:
        rid = self._current_rid()
        r = self._mgr.get(rid)
        if r:
            r.name = self._name_edit.text().strip() or f"STRATEGICREGION_{rid}"
            self._refresh_list()

    def _on_weather_changed(self, index: int) -> None:
        rid = self._current_rid()
        r = self._mgr.get(rid)
        if r:
            r.weather_preset = self._weather_combo.currentData() or "temperate"

    def _on_naval_changed(self, index: int) -> None:
        rid = self._current_rid()
        r = self._mgr.get(rid)
        if r:
            r.naval_terrain = self._naval_combo.currentData() or ""

    # ─────────── 拾取 ───────────

    def _on_pick_toggled(self, on: bool) -> None:
        rid = self._current_rid()
        if on and rid <= 0:
            self._pick_btn.setChecked(False)
            QMessageBox.warning(self, tr("dlg_error"), tr("sr_dlg_err_select_region"))
            return
        self._pick_on = on
        if on:
            self._pick_btn.setText(tr("sr_dlg_stop_pick"))
            self._status.setText(tr("sr_dlg_pick_status_fmt", rid))
        else:
            self._pick_btn.setText(tr("sr_dlg_start_pick"))
            self._status.setText("")
        self.pick_mode_changed.emit(on, rid)

    def notify_assigned(self, pid: int) -> None:
        """主窗口指派省份后回调."""
        rid = self._current_rid()
        r = self._mgr.get(rid)
        if r:
            self._prov_count_label.setText(tr("sr_dlg_province_count_fmt", len(r.province_ids)))
            self._status.setText(tr("sr_dlg_assigned_fmt", pid, rid))
        self._refresh_list()

    def closeEvent(self, event) -> None:
        if self._pick_on:
            self.pick_mode_changed.emit(False, 0)
            self._pick_on = False
        super().closeEvent(event)
