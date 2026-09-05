"""province feature 页面 — 独立 QWidget, 不依赖 ToolPanel.

默认点击 = 查看省份数据
合并/扩张 需要手动开启，操作完自动关闭回到查看模式。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QSlider, QButtonGroup, QSpinBox,
)

from ui.styles import (
    make_section as _make_section,
    make_hint as _make_hint,
    _DIM, _ACCENT, _BORDER, _SECTION_STYLE, _LABEL_STYLE, _DIM_LABEL_STYLE,
    _PRIMARY_BTN_STYLE, _SECONDARY_BTN_STYLE, _LINEEDIT_STYLE,
    _TOOL_BTN_STYLE, _SLIDER_STYLE, _SPINBOX_STYLE,
)
from ui.i18n import tr, tr_pair

# 模式激活时的按钮样式（醒目橙色）
_ACTIVE_MODE_BTN_STYLE = """
    QPushButton {
        background: #e67e22;
        border: 2px solid #f39c12;
        color: white;
        padding: 7px 12px;
        font-size: 13px;
        font-weight: bold;
        border-radius: 5px;
    }
    QPushButton:hover {
        background: #f39c12;
    }
"""

# 模式激活时的提示样式（橙色背景）
_ACTIVE_HINT_STYLE = """
    color: white;
    font-size: 13px;
    font-weight: bold;
    padding: 10px;
    background: rgba(230, 126, 34, 0.25);
    border: 1px solid rgba(230, 126, 34, 0.5);
    border-radius: 4px;
"""

_NORMAL_HINT_STYLE = f"color: {_DIM}; font-size: 12px; padding: 8px;"




class ProvincePage(QWidget):
    """省份编辑页面."""

    # 输出信号
    split_mode_toggled = pyqtSignal(bool)
    lasso_province_toggled = pyqtSignal(bool)
    merge_mode_toggled = pyqtSignal(bool)
    find_province_requested = pyqtSignal(int)
    province_paint_mode_changed = pyqtSignal(str)
    province_brush_size_changed = pyqtSignal(int)
    new_province_requested = pyqtSignal()
    generate_provinces_requested = pyqtSignal(str, int)
    validate_requested = pyqtSignal()
    import_ref_requested = pyqtSignal()
    auto_provinces_from_ref_requested = pyqtSignal()
    random_split_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        # ── 省份查找（顶部）──
        find_row = QHBoxLayout()
        find_row.setSpacing(4)
        find_icon = QLabel("🔍")
        find_icon.setStyleSheet(f"color: {_DIM}; font-size: 14px; padding: 0 4px;")
        find_row.addWidget(find_icon)

        self._find_input = QLineEdit()
        self._find_input.setPlaceholderText(tr("province_search_placeholder"))
        self._find_input.setStyleSheet(_LINEEDIT_STYLE)
        self._find_input.setValidator(QIntValidator(1, 99999999, self))
        self._find_input.returnPressed.connect(self._on_find_clicked)
        find_row.addWidget(self._find_input, stretch=1)

        self._find_btn = QPushButton(tr("province_btn_find"))
        self._find_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._find_btn.setToolTip(tr("province_btn_find_tip"))
        self._find_btn.clicked.connect(self._on_find_clicked)
        find_row.addWidget(self._find_btn)
        lay.addLayout(find_row)

        # 提示 (动态更新)
        self._province_hint = QLabel(tr("province_hint_default"))
        self._province_hint.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 8px;")
        self._province_hint.setWordWrap(True)
        lay.addWidget(self._province_hint)

        # ── 省份信息（单行紧凑） ──
        self._prov_info_label = QLabel(tr("province_info_compact_default"))
        self._prov_info_label.setStyleSheet(
            f"color: #aaa; font-size: 11px; padding: 4px 8px;"
            f" background: #1a1a22; border: 1px solid #2a2a3c; border-radius: 4px;"
        )
        lay.addWidget(self._prov_info_label)

        # ── 省份统计 ──
        self._stats_label = QLabel()
        self._stats_label.setWordWrap(True)
        self._stats_label.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 4px 8px;")
        lay.addWidget(self._stats_label)

        # ── Province generation (above manual province drawing) ──
        generation_box = _make_section(tr("province_section_generation"))

        count_row = QHBoxLayout()
        count_label = QLabel(tr("province_label_generation_count"))
        count_label.setStyleSheet(_LABEL_STYLE)
        count_row.addWidget(count_label)
        self._province_count_spin = QSpinBox()
        self._province_count_spin.setRange(100, 20000)
        self._province_count_spin.setSingleStep(500)
        self._province_count_spin.setValue(12000)
        self._province_count_spin.setStyleSheet(_SPINBOX_STYLE)
        count_row.addWidget(self._province_count_spin)
        generation_box.layout().addLayout(count_row)

        sea_row = QHBoxLayout()
        sea_label = QLabel(tr("province_label_sea_density"))
        sea_label.setStyleSheet(_LABEL_STYLE)
        sea_row.addWidget(sea_label)
        self._sea_density_label = QLabel("15%")
        self._sea_density_label.setStyleSheet(_DIM_LABEL_STYLE)
        sea_row.addStretch()
        sea_row.addWidget(self._sea_density_label)
        generation_box.layout().addLayout(sea_row)

        self._sea_density_slider = QSlider(Qt.Orientation.Horizontal)
        self._sea_density_slider.setRange(5, 100)
        self._sea_density_slider.setValue(15)
        self._sea_density_slider.setStyleSheet(_SLIDER_STYLE)
        self._sea_density_slider.valueChanged.connect(
            lambda value: self._sea_density_label.setText(f"{value}%")
        )
        generation_box.layout().addWidget(self._sea_density_slider)

        lake_row = QHBoxLayout()
        lake_label = QLabel(tr("province_label_lake_density"))
        lake_label.setStyleSheet(_LABEL_STYLE)
        lake_row.addWidget(lake_label)
        self._lake_density_label = QLabel("30%")
        self._lake_density_label.setStyleSheet(_DIM_LABEL_STYLE)
        lake_row.addStretch()
        lake_row.addWidget(self._lake_density_label)
        generation_box.layout().addLayout(lake_row)

        self._lake_density_slider = QSlider(Qt.Orientation.Horizontal)
        self._lake_density_slider.setRange(10, 100)
        self._lake_density_slider.setValue(30)
        self._lake_density_slider.setStyleSheet(_SLIDER_STYLE)
        self._lake_density_slider.valueChanged.connect(
            lambda value: self._lake_density_label.setText(f"{value}%")
        )
        generation_box.layout().addWidget(self._lake_density_slider)

        generation_box.layout().addWidget(
            _make_hint(tr("province_generation_hint"))
        )
        self._generation_buttons: dict[str, QPushButton] = {}
        for scope, label_key, tip_key, style in (
            ("all", "province_btn_generate_all", "province_btn_generate_all_tip", _PRIMARY_BTN_STYLE),
            ("land", "province_btn_generate_land", "province_btn_generate_land_tip", _SECONDARY_BTN_STYLE),
            ("sea", "province_btn_generate_sea", "province_btn_generate_sea_tip", _SECONDARY_BTN_STYLE),
            ("lake", "province_btn_generate_lake", "province_btn_generate_lake_tip", _SECONDARY_BTN_STYLE),
        ):
            button = QPushButton(tr(label_key))
            button.setStyleSheet(style)
            button.setToolTip(tr(tip_key))
            button.clicked.connect(
                lambda _checked=False, selected_scope=scope: self._on_generate_provinces(
                    selected_scope
                )
            )
            self._generation_buttons[scope] = button
            generation_box.layout().addWidget(button)

        validate_button = QPushButton(tr("province_btn_validate"))
        validate_button.setStyleSheet(_SECONDARY_BTN_STYLE)
        validate_button.clicked.connect(self.validate_requested.emit)
        self._validate_btn = validate_button
        generation_box.layout().addWidget(validate_button)
        lay.addWidget(generation_box)

        # ── 手动画省份（与自动生成共用同一 province_map）──
        draw_box = _make_section(tr("province_section_manual_draw"))

        ref_row = QHBoxLayout()
        ref_btn = QPushButton(tr("province_btn_import_ref"))
        ref_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        ref_btn.setToolTip(tr("province_btn_import_ref_tip"))
        ref_btn.clicked.connect(self.import_ref_requested.emit)
        ref_row.addWidget(ref_btn)
        ref_hint = QLabel(tr("province_ref_hint"))
        ref_hint.setWordWrap(True)
        ref_hint.setStyleSheet(_DIM_LABEL_STYLE)
        ref_row.addWidget(ref_hint, 1)
        draw_box.layout().addLayout(ref_row)

        auto_ref_btn = QPushButton(tr("province_btn_auto_ref"))
        auto_ref_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        auto_ref_btn.setToolTip(tr("province_btn_auto_ref_tip"))
        auto_ref_btn.clicked.connect(self.auto_provinces_from_ref_requested.emit)
        draw_box.layout().addWidget(auto_ref_btn)

        paint_row = QHBoxLayout()
        paint_row.setSpacing(3)
        self._paint_group = QButtonGroup(self)
        self._paint_group.setExclusive(True)
        self._select_btn = QPushButton(tr("province_tool_select"))
        self._paint_brush_btn = QPushButton(tr("province_tool_brush"))
        self._paint_fill_btn = QPushButton(tr("province_tool_fill"))
        for btn, mode, tip_key in (
            (self._select_btn, "select", "province_tool_select_tip"),
            (self._paint_brush_btn, "brush", "province_tool_brush_tip"),
            (self._paint_fill_btn, "fill", "province_tool_fill_tip"),
        ):
            btn.setCheckable(True)
            btn.setProperty("paint_mode", mode)
            btn.setStyleSheet(_TOOL_BTN_STYLE)
            btn.setToolTip(tr(tip_key))
            self._paint_group.addButton(btn)
            paint_row.addWidget(btn)
        self._select_btn.setChecked(True)
        self._paint_group.buttonClicked.connect(self._on_paint_tool_clicked)
        draw_box.layout().addLayout(paint_row)

        self._new_province_btn = QPushButton(tr("province_btn_new"))
        self._new_province_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._new_province_btn.setToolTip(tr("province_btn_new_tip"))
        self._new_province_btn.clicked.connect(self._on_new_province)
        draw_box.layout().addWidget(self._new_province_btn)

        brush_row = QHBoxLayout()
        brush_label = QLabel(tr("province_label_brush_size"))
        brush_label.setStyleSheet(_LABEL_STYLE)
        brush_row.addWidget(brush_label)
        brush_row.addStretch()
        self._brush_value_label = QLabel("9px")
        self._brush_value_label.setStyleSheet(_DIM_LABEL_STYLE)
        brush_row.addWidget(self._brush_value_label)
        draw_box.layout().addLayout(brush_row)
        self._brush_slider = QSlider(Qt.Orientation.Horizontal)
        self._brush_slider.setRange(1, 100)
        self._brush_slider.setValue(9)
        self._brush_slider.setStyleSheet(_SLIDER_STYLE)
        self._brush_slider.valueChanged.connect(self._on_brush_size)
        draw_box.layout().addWidget(self._brush_slider)

        self._manual_target_label = QLabel(tr("province_target_none"))
        self._manual_target_label.setWordWrap(True)
        self._manual_target_label.setStyleSheet(_DIM_LABEL_STYLE)
        draw_box.layout().addWidget(self._manual_target_label)
        lay.addWidget(draw_box)

        # ── 工具按钮（横排） ──
        tools_box = _make_section(tr("province_section_tools"))
        tools_row = QHBoxLayout()

        self._merge_btn = QPushButton(tr("province_btn_merge"))
        self._merge_btn.setCheckable(True)
        self._merge_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._merge_btn.setToolTip(tr("province_btn_merge_tip"))
        tools_row.addWidget(self._merge_btn)

        self._expand_btn = QPushButton(tr("province_btn_expand"))
        self._expand_btn.setCheckable(True)
        self._expand_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._expand_btn.setToolTip(tr("province_btn_expand_tip"))
        tools_row.addWidget(self._expand_btn)

        self._split_btn = QPushButton(tr("province_btn_split"))
        self._split_btn.setCheckable(True)
        self._split_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._split_btn.setToolTip(tr("province_btn_split_tip"))
        tools_row.addWidget(self._split_btn)

        tools_box.layout().addLayout(tools_row)

        random_row = QHBoxLayout()
        random_label = QLabel(tr("province_random_target_label"))
        random_label.setStyleSheet(_LABEL_STYLE)
        random_row.addWidget(random_label)
        self._random_split_count = QSpinBox()
        self._random_split_count.setRange(2, 1000)
        self._random_split_count.setValue(4)
        self._random_split_count.setToolTip(tr("province_random_target_tip"))
        random_row.addWidget(self._random_split_count)
        random_btn = QPushButton(tr("province_btn_random_split"))
        random_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        random_btn.setToolTip(tr("province_btn_random_split_tip"))
        random_btn.clicked.connect(
            lambda: self.random_split_requested.emit(self._random_split_count.value())
        )
        random_row.addWidget(random_btn, 1)
        tools_box.layout().addLayout(random_row)
        lay.addWidget(tools_box)

        # ── 信号连接 ──
        self._merge_btn.toggled.connect(self._on_merge_toggled)
        self._expand_btn.toggled.connect(self._on_expand_toggled)
        self._split_btn.toggled.connect(self._on_split_toggled)

        lay.addStretch()

    # ── 槽函数 ──
    def _clear_other_modes(self, *keep: QPushButton) -> None:
        """关闭除 keep 之外的所有模式按钮。"""
        for btn in (self._merge_btn, self._expand_btn, self._split_btn):
            if btn not in keep and btn.isChecked():
                btn.setChecked(False)

    def _on_merge_toggled(self, on: bool) -> None:
        if on:
            self._clear_other_modes(self._merge_btn)
            self._select_btn.setChecked(True)
            self.province_paint_mode_changed.emit("select")
        self.merge_mode_toggled.emit(on)
        self._update_mode_visuals()

    def _on_expand_toggled(self, on: bool) -> None:
        if on:
            self._clear_other_modes(self._expand_btn)
            self._select_btn.setChecked(True)
            self.province_paint_mode_changed.emit("select")
        self.lasso_province_toggled.emit(on)
        self._update_mode_visuals()

    def _on_split_toggled(self, on: bool) -> None:
        if on:
            self._clear_other_modes(self._split_btn)
            self._select_btn.setChecked(True)
            self.province_paint_mode_changed.emit("select")
        self.split_mode_toggled.emit(on)
        self._update_mode_visuals()

    def _on_paint_tool_clicked(self, button: QPushButton) -> None:
        self._clear_other_modes()
        self.province_paint_mode_changed.emit(str(button.property("paint_mode")))
        self._update_mode_visuals()

    def _on_new_province(self) -> None:
        # Creating always enters brush mode so the next stroke gives the ID pixels.
        self._paint_brush_btn.setChecked(True)
        self._clear_other_modes()
        self.province_paint_mode_changed.emit("brush")
        self.new_province_requested.emit()
        self._update_mode_visuals()

    def _on_generate_provinces(self, scope: str) -> None:
        self.generate_provinces_requested.emit(scope, self._province_count_spin.value())

    def get_generation_params(self) -> dict:
        """Return the province-generation controls shared by all scopes."""
        return {
            "target_count": self._province_count_spin.value(),
            "sea_scale": self._sea_density_slider.value() / 100.0,
            "lake_scale": self._lake_density_slider.value() / 100.0,
        }

    def _on_brush_size(self, value: int) -> None:
        self._brush_value_label.setText(f"{value}px")
        self.province_brush_size_changed.emit(value)

    def _on_find_clicked(self) -> None:
        txt = self._find_input.text().strip()
        if not txt:
            return
        try:
            pid = int(txt)
        except ValueError:
            return
        if pid <= 0:
            return
        self.find_province_requested.emit(pid)
        # 重置输入框红色边框（如果上次查无）
        self._find_input.setStyleSheet(_LINEEDIT_STYLE)

    def mark_find_not_found(self) -> None:
        """外部 handler 在 ID 不存在时调用 — 输入框边框变红。"""
        self._find_input.setStyleSheet(
            _LINEEDIT_STYLE + "QLineEdit { border: 1px solid #ef4444; }"
        )

    def _update_mode_visuals(self) -> None:
        """根据当前激活模式更新按钮样式和提示条。"""
        merging = self._merge_btn.isChecked()
        expanding = self._expand_btn.isChecked()
        splitting = self._split_btn.isChecked()
        painting = self._paint_brush_btn.isChecked()
        filling = self._paint_fill_btn.isChecked()

        # 按钮样式：激活时变橙色
        for btn, active in [
            (self._merge_btn, merging),
            (self._expand_btn, expanding),
            (self._split_btn, splitting),
        ]:
            btn.setStyleSheet(_ACTIVE_MODE_BTN_STYLE if active else _SECONDARY_BTN_STYLE)

        # 提示条
        if merging:
            self._province_hint.setText(tr("province_hint_merge"))
            self._province_hint.setStyleSheet(_ACTIVE_HINT_STYLE)
        elif expanding:
            self._province_hint.setText(tr("province_hint_expand"))
            self._province_hint.setStyleSheet(_ACTIVE_HINT_STYLE)
        elif splitting:
            self._province_hint.setText(tr("province_hint_split"))
            self._province_hint.setStyleSheet(_ACTIVE_HINT_STYLE)
        elif painting:
            self._province_hint.setText(tr("province_hint_paint"))
            self._province_hint.setStyleSheet(_ACTIVE_HINT_STYLE)
        elif filling:
            self._province_hint.setText(tr("province_hint_fill"))
            self._province_hint.setStyleSheet(_ACTIVE_HINT_STYLE)
        else:
            self._province_hint.setText(tr("province_hint_default"))
            self._province_hint.setStyleSheet(_NORMAL_HINT_STYLE)

    # ── 公共更新方法 ──
    def update_province_info(
        self, pid: int, ptype: str, terrain: str, pixels: int, coastal: bool
    ) -> None:
        """更新省份信息面板（单行紧凑格式，加字段标签）"""
        parts = [
            f"ID: {pid}",
            f"{tr('province_info_type')}: {ptype}",
            f"{tr('province_info_terrain')}: {terrain}",
            f"{pixels}px",
        ]
        if coastal:
            parts.append(tr("province_info_coastal"))
        self._prov_info_label.setText(" | ".join(parts))
        self._manual_target_label.setText(tr("province_target_selected", pid=pid))

    def update_manual_target(self, pid: int, is_new: bool = False) -> None:
        """Show which ID the brush/fill tools currently paint."""
        if pid <= 0:
            self._manual_target_label.setText(tr("province_target_none"))
        elif is_new:
            self._manual_target_label.setText(tr("province_target_new", pid=pid))
        else:
            self._manual_target_label.setText(tr("province_target_selected", pid=pid))

    def update_province_gaps(self, gap_ids: list[int]) -> None:
        """更新省份 ID 空洞提示。"""
        if not gap_ids:
            self._stats_label.setText("")
            self._stats_label.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 4px 8px;")
            return

        if len(gap_ids) <= 10:
            ids_str = ", ".join(str(i) for i in gap_ids)
        else:
            ids_str = ", ".join(str(i) for i in gap_ids[:10]) + tr_pair(f" ... 共 {len(gap_ids)} 个", f" ... {len(gap_ids)} total")

        self._stats_label.setText(
            tr_pair(
                f"缺失省份 ID: {ids_str}\n需要用切割或增量生成补回",
                f"Missing province IDs: {ids_str}\nRestore them by splitting or incremental generation",
            )
        )
        self._stats_label.setStyleSheet(
            "color: #f59e0b; font-size: 12px; font-weight: bold; padding: 8px;"
            " background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3);"
            " border-radius: 4px;"
        )
