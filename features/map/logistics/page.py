"""后勤 feature 侧边栏页面 — 独立 QWidget, 不依赖 ToolPanel.

三个 section:
1. 相邻关系 (adjacencies) — 海峡/运河/不可通行
2. 铁路 + 补给 — 统一色块/图标选择 + 点击省份
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QButtonGroup,
)

from ui.i18n import tr
from ui.styles import (
    make_section as _make_section,
    _DIM_LABEL_STYLE,
    _PRIMARY_BTN_STYLE, _SECONDARY_BTN_STYLE,
)

# 铁路等级对应颜色 (与 renderer 一致)
_RAIL_COLORS = {
    0: "#323232",   # 擦除
    1: "#646478",   # 灰蓝
    2: "#508C50",   # 绿
    3: "#C8AA32",   # 金黄
    4: "#D27832",   # 橙
    5: "#D23232",   # 红
}


# 按钮 ID 约定: 0-5 = 铁路等级, 10 = 补给节点, 11 = 擦除补给
_ID_SUPPLY = 10
_ID_SUPPLY_ERASE = 11


class LogisticsPage(QWidget):
    """后勤系统页面."""

    # 输出信号
    open_adjacency_dialog_requested = pyqtSignal()
    open_railway_list_requested = pyqtSignal()
    generate_logistics_requested = pyqtSignal()
    logistics_railway_level_changed = pyqtSignal(int)
    logistics_supply_pick_toggled = pyqtSignal(bool, bool)  # (on, erase)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        tip = QLabel(tr("logistics_tip"))
        tip.setStyleSheet(_DIM_LABEL_STYLE)
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # ── 相邻关系 ──
        adj_box = _make_section(tr("logistics_adj_section"))
        adj_lay = adj_box.layout()

        self._logi_adj_status = QLabel(tr("logistics_adj_count", 0))
        self._logi_adj_status.setStyleSheet(_DIM_LABEL_STYLE)
        adj_lay.addWidget(self._logi_adj_status)

        adj_btn = QPushButton(tr("logistics_adj_editor_btn"))
        adj_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        adj_btn.clicked.connect(lambda: self.open_adjacency_dialog_requested.emit())
        adj_lay.addWidget(adj_btn)

        lay.addWidget(adj_box)

        # ── 铁路 + 补给 ──
        tool_box = _make_section(tr("logistics_rail_supply_section"))
        tool_lay = tool_box.layout()

        self._logi_rail_status = QLabel(tr("logistics_rail_count", 0))
        self._logi_rail_status.setStyleSheet(_DIM_LABEL_STYLE)
        tool_lay.addWidget(self._logi_rail_status)

        self._logi_sup_status = QLabel(tr("logistics_supply_count", 0))
        self._logi_sup_status.setStyleSheet(_DIM_LABEL_STYLE)
        tool_lay.addWidget(self._logi_sup_status)

        lbl = QLabel(tr("logistics_click_province_hint"))
        lbl.setStyleSheet(_DIM_LABEL_STYLE)
        tool_lay.addWidget(lbl)

        # 统一按钮组
        self._tool_btn_group = QButtonGroup(self)

        # 铁路色块行
        rail_row = QHBoxLayout()
        rail_row.setSpacing(4)
        rail_lbl = QLabel(tr("logistics_rail_label"))
        rail_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        rail_lbl.setFixedWidth(30)
        rail_row.addWidget(rail_lbl)

        _btn_base = (
            "QPushButton {{ background: {bg}; color: white;"
            " font-weight: bold; font-size: 14px;"
            " border: 2px solid #555; border-radius: 4px; }}"
            "QPushButton:checked {{ border: 3px solid #FFE040; }}"
            "QPushButton:hover {{ border: 2px solid #AAA; }}"
        )

        for level in range(6):  # 0=擦除, 1-5
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedSize(34, 34)
            hex_color = _RAIL_COLORS[level]
            if level == 0:
                btn.setText("×")
                btn.setToolTip(tr("logistics_rail_erase_tip"))
            else:
                btn.setText(str(level))
                btn.setToolTip(tr("logistics_rail_level_tip", level))
            btn.setStyleSheet(_btn_base.format(bg=hex_color))
            self._tool_btn_group.addButton(btn, level)
            rail_row.addWidget(btn)

        tool_lay.addLayout(rail_row)

        # 补给图标行
        sup_row = QHBoxLayout()
        sup_row.setSpacing(4)
        sup_lbl = QLabel(tr("logistics_supply_label"))
        sup_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        sup_lbl.setFixedWidth(30)
        sup_row.addWidget(sup_lbl)

        sup_btn = QPushButton("◆+")
        sup_btn.setCheckable(True)
        sup_btn.setFixedSize(34, 34)
        sup_btn.setToolTip(tr("logistics_supply_place_tip"))
        sup_btn.setStyleSheet(
            "QPushButton { background: #2CA02C; color: white;"
            " font-weight: bold; font-size: 13px;"
            " border: 2px solid #555; border-radius: 4px; }"
            "QPushButton:checked { border: 3px solid #FFE040; }"
            "QPushButton:hover { border: 2px solid #AAA; }"
        )
        self._tool_btn_group.addButton(sup_btn, _ID_SUPPLY)
        sup_row.addWidget(sup_btn)

        sup_erase_btn = QPushButton("◆×")
        sup_erase_btn.setCheckable(True)
        sup_erase_btn.setFixedSize(34, 34)
        sup_erase_btn.setToolTip(tr("logistics_supply_erase_tip"))
        sup_erase_btn.setStyleSheet(
            "QPushButton { background: #555; color: #ccc;"
            " font-weight: bold; font-size: 13px;"
            " border: 2px solid #555; border-radius: 4px; }"
            "QPushButton:checked { border: 3px solid #FFE040; }"
            "QPushButton:hover { border: 2px solid #AAA; }"
        )
        self._tool_btn_group.addButton(sup_erase_btn, _ID_SUPPLY_ERASE)
        sup_row.addWidget(sup_erase_btn)

        sup_row.addStretch()
        tool_lay.addLayout(sup_row)

        # 默认选中铁路等级 3
        self._tool_btn_group.button(3).setChecked(True)
        self._tool_btn_group.idClicked.connect(self._on_tool_clicked)

        rail_list_btn = QPushButton(tr("logistics_rail_list_btn"))
        rail_list_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        rail_list_btn.clicked.connect(lambda: self.open_railway_list_requested.emit())
        tool_lay.addWidget(rail_list_btn)

        lay.addWidget(tool_box)

        generate_btn = QPushButton(tr("logistics_generate_button"))
        generate_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        generate_btn.clicked.connect(self.generate_logistics_requested.emit)
        lay.addWidget(generate_btn)

        lay.addStretch(1)

    def _on_tool_clicked(self, btn_id: int) -> None:
        if btn_id <= 5:
            # 铁路模式 — 关闭补给
            self.logistics_supply_pick_toggled.emit(False, False)
            self.logistics_railway_level_changed.emit(btn_id)
        elif btn_id == _ID_SUPPLY:
            self.logistics_supply_pick_toggled.emit(True, False)
        elif btn_id == _ID_SUPPLY_ERASE:
            self.logistics_supply_pick_toggled.emit(True, True)
