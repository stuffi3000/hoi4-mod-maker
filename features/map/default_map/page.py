"""Map configuration (default.map) page — independent QWidget, does not depend on ToolPanel.

Editable: Tree Palette Index / River Max Level."""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QListWidget, QScrollArea,
)

from ui.i18n import tr
from ui.styles import (
    make_section as _make_section,
    _DIM_LABEL_STYLE, _LABEL_STYLE, _SPINBOX_STYLE, _LIST_STYLE,
    _SECONDARY_BTN_STYLE,
)


class DefaultMapPage(QWidget):
    """Map configuration page."""

    # Output signal
    default_map_river_changed = pyqtSignal(int)
    default_map_tree_add_requested = pyqtSignal()
    default_map_tree_del_requested = pyqtSignal()
    default_map_tree_reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        tip = QLabel(tr("defmap_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet(_DIM_LABEL_STYLE)
        lay.addWidget(tip)

        # ── River configuration ──
        river_box = _make_section(tr("defmap_section_river"))
        rl = river_box.layout()

        river_row = QHBoxLayout()
        river_lbl = QLabel(tr("defmap_river_max_label"))
        river_lbl.setStyleSheet(_LABEL_STYLE)
        river_row.addWidget(river_lbl)
        self._dm_river_max = QSpinBox()
        self._dm_river_max.setRange(1, 10)
        self._dm_river_max.setValue(5)
        self._dm_river_max.setStyleSheet(_SPINBOX_STYLE)
        self._dm_river_max.valueChanged.connect(
            lambda v: self.default_map_river_changed.emit(v)
        )
        river_row.addWidget(self._dm_river_max)
        rl.addLayout(river_row)
        lay.addWidget(river_box)

        # ── Tree Palette ──
        tree_box = _make_section(tr("defmap_section_trees"))
        tl = tree_box.layout()

        self._dm_tree_list = QListWidget()
        self._dm_tree_list.setStyleSheet(_LIST_STYLE)
        self._dm_tree_list.setMinimumHeight(150)
        tl.addWidget(self._dm_tree_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton(tr("defmap_add_btn"))
        add_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        add_btn.clicked.connect(lambda: self.default_map_tree_add_requested.emit())
        del_btn = QPushButton(tr("defmap_delete_btn"))
        del_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        del_btn.clicked.connect(lambda: self.default_map_tree_del_requested.emit())
        reset_btn = QPushButton(tr("defmap_reset_btn"))
        reset_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        reset_btn.clicked.connect(lambda: self.default_map_tree_reset_requested.emit())
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(reset_btn)
        tl.addLayout(btn_row)
        lay.addWidget(tree_box)

        lay.addStretch(1)
        scroll.setWidget(page)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)
