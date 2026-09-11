"""Building level editing dialog box for each province.

HOI4 allows configuring certain buildings within the state for specific provinces (vs. state-level statistical buildings):
- bunker — land fortification
- coastal_bunker — coastal fortifications
- naval_base — naval base (must be coastal)

Data exists StateData.province_buildings: dict[pid, dict[building_name, level]]
Nested `pid = { building = level }` format in buildings blocks exported to history/states/*.txt.

Reference: Reference/State modding.txt Province-level building fields"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton,
    QScrollArea, QWidget, QGridLayout, QFrame,
)

from ui.i18n import tr


# Allowed provincial building types + level cap
# Reference common/buildings/00_buildings.txt
_PROVINCE_BUILDINGS = [
    ("bunker", "prov_bld_bunker", 5),
    ("coastal_bunker", "prov_bld_coastal", 5),
    ("naval_base", "prov_bld_naval", 10),
]


class ProvinceBuildingsDialog(QDialog):
    """Configure bunker / coastal_bunker / naval_base for each land province of the selected state."""

    def __init__(self, state, land_province_ids: list[int], parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._land_pids = list(land_province_ids)
        self.setWindowTitle(tr("prov_bld_title_fmt", state.name, state.id))
        self.setMinimumSize(440, 480)

        # The spinbox reference used to collect each row: {(pid, building): spin}
        self._spins: dict[tuple[int, str], QSpinBox] = {}

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        tip = QLabel(tr("prov_bld_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(tip)

        # scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #2a3a55; }")

        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)

        # Header
        grid.addWidget(QLabel(f"<b>{tr('prov_bld_province_id')}</b>"), 0, 0)
        for i, (_, display, _max) in enumerate(_PROVINCE_BUILDINGS):
            grid.addWidget(QLabel(f"<b>{tr(display)}</b>"), 0, i + 1)

        # One line for each land province
        for row, pid in enumerate(self._land_pids, start=1):
            grid.addWidget(QLabel(str(pid)), row, 0)
            current_map = self._state.province_buildings.get(pid, {})
            for col, (bname, _display, bmax) in enumerate(_PROVINCE_BUILDINGS):
                spin = QSpinBox()
                spin.setRange(0, bmax)
                spin.setValue(int(current_map.get(bname, 0)))
                spin.setFixedWidth(60)
                grid.addWidget(spin, row, col + 1)
                self._spins[(pid, bname)] = spin

        grid.setRowStretch(len(self._land_pids) + 1, 1)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # bottom button
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton(tr("prov_bld_save"))
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton(tr("prov_bld_cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def _on_accept(self) -> None:
        """Write the spin value back to state.province_buildings."""
        new_pb: dict[int, dict[str, int]] = {}
        for (pid, bname), spin in self._spins.items():
            v = int(spin.value())
            if v > 0:
                new_pb.setdefault(pid, {})[bname] = v
        self._state.province_buildings = new_pb
        self.accept()
