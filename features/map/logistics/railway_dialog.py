"""
铁路列表对话框 — 查看/删除已画的铁路.

新建铁路走侧边栏的"启用铁路画笔"按钮 + 画布工具 (RailwayDrawTool).
这里只负责查看和删除.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton,
)

from domain.managers.railway import RailwayManager
from ui.i18n import tr


class RailwayDialog(QDialog):

    changed = pyqtSignal()

    def __init__(self, railway_mgr: RailwayManager, parent=None) -> None:
        super().__init__(parent)
        self._mgr = railway_mgr
        self.setWindowTitle(tr("rail_dlg_title"))
        self.setMinimumSize(360, 420)
        self.setWindowFlags(self.windowFlags() | Qt.Tool)

        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        tip = QLabel(tr("rail_dlg_hint"))
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(tip)

        self._list = QListWidget()
        root.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        del_btn = QPushButton(tr("rail_dlg_delete_selected"))
        del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(del_btn)
        clear_btn = QPushButton(tr("rail_dlg_clear_all"))
        clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch(1)
        close_btn = QPushButton(tr("rail_dlg_close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _refresh_list(self) -> None:
        self._list.clear()
        for i, e in enumerate(self._mgr.get_all()):
            label = (
                f"#{i + 1}  level {e.level}  "
                f"{tr('rail_dlg_list_item_fmt', len(e.province_ids))}  "
                f"[{' → '.join(str(p) for p in e.province_ids[:5])}"
                f"{' ...' if len(e.province_ids) > 5 else ''}]"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, i)
            self._list.addItem(item)

    def _on_delete(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        if self._mgr.remove_at(row):
            self._refresh_list()
            self.changed.emit()

    def _on_clear(self) -> None:
        self._mgr.clear()
        self._refresh_list()
        self.changed.emit()
