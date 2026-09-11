"""State Details Dialog — Edit advanced fields of a State:
- impassable/controller/local_supplies
- resources (6 strategic resources)
- buildings (state building level)
- extra_cores / claims (TAG list)

Provincial-level buildings (bunker/coastal_bunker/naval_base) are not exposed in this UI yet.
It needs to be edited by province, and special province construction tools will be made in the next iteration."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox,
    QPushButton, QGroupBox, QListWidget, QInputDialog, QTabWidget, QWidget,
    QScrollArea,
)

from ui.i18n import tr


# HOI4 strategic resources (vanilla 1.18 full list)
RESOURCE_NAMES = ["oil", "aluminium", "rubber", "tungsten", "steel", "chromium", "coal"]
RESOURCE_LABELS = {
    "oil": "state_dlg_res_oil", "aluminium": "state_dlg_res_aluminium",
    "rubber": "state_dlg_res_rubber", "tungsten": "state_dlg_res_tungsten",
    "steel": "state_dlg_res_steel", "chromium": "state_dlg_res_chromium",
    "coal": "state_dlg_res_coal",
}

# HOI4 state-level building (value 0 = do not write)
STATE_BUILDINGS = [
    "infrastructure",
    "arms_factory",
    "industrial_complex",
    "dockyard",
    "air_base",
    "anti_air_building",
    "radar_station",
    "synthetic_refinery",
    "fuel_silo",
    "nuclear_reactor",
    "rocket_site",
    "mass_transit",
    "supply_node",
]
BUILDING_LABELS = {
    "infrastructure": "state_dlg_bld_infrastructure",
    "arms_factory": "state_dlg_bld_arms_factory",
    "industrial_complex": "state_dlg_bld_industrial_complex",
    "dockyard": "state_dlg_bld_dockyard",
    "air_base": "state_dlg_bld_air_base",
    "anti_air_building": "state_dlg_bld_anti_air",
    "radar_station": "state_dlg_bld_radar",
    "synthetic_refinery": "state_dlg_bld_synthetic",
    "fuel_silo": "state_dlg_bld_fuel_silo",
    "nuclear_reactor": "state_dlg_bld_nuclear",
    "rocket_site": "state_dlg_bld_rocket",
    "mass_transit": "state_dlg_bld_mass_transit",
    "supply_node": "state_dlg_bld_supply_node",
}
BUILDING_MAX = {
    "infrastructure": 5,
    "air_base": 10,
    "anti_air_building": 5,
    "radar_station": 4,
    "nuclear_reactor": 3,
    "rocket_site": 10,
    "mass_transit": 3,
    "supply_node": 1,
    # Others default 30 (vanilla actual limit depends on state_category)
}


class StateDetailDialog(QDialog):
    """Edit advanced fields of a single State. Modal."""

    def __init__(self, state, country_tags: list[str], parent=None):
        super().__init__(parent)
        self._state = state
        self._country_tags = country_tags
        self.setWindowTitle(tr("state_dlg_title_fmt", state.name, state.id))
        self.setMinimumSize(520, 600)

        self._build_ui()
        self._load_from_state()

    # ─────────── UI construction ───────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # Each tab package scroll area: the content (building 13 lines/VP multi-line) can be scrolled when it exceeds the window height and will no longer be cropped
        tabs.addTab(self._wrap_scroll(self._build_basic_tab()), tr("state_dlg_tab_basic"))
        tabs.addTab(self._wrap_scroll(self._build_resources_tab()), tr("state_dlg_tab_resources"))
        tabs.addTab(self._wrap_scroll(self._build_buildings_tab()), tr("state_dlg_tab_buildings"))
        tabs.addTab(self._wrap_scroll(self._build_cores_tab()), tr("state_dlg_tab_cores"))

        # bottom button
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton(tr("state_dlg_save"))
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton(tr("state_dlg_cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    @staticmethod
    def _wrap_scroll(inner: QWidget) -> QScrollArea:
        """The tab content covers the scroll area, and the scroll bar appears when the height is not enough."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(inner)
        return area

    def _build_basic_tab(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(tr("state_dlg_name_hint"))
        lay.addRow(tr("state_dlg_name_label"), self._name_edit)

        self._name_en_edit = QLineEdit()
        self._name_en_edit.setPlaceholderText(tr("state_dlg_name_en_hint"))
        lay.addRow(tr("state_dlg_name_en_label"), self._name_en_edit)

        self._manpower_spin = QSpinBox()
        self._manpower_spin.setRange(0, 100_000_000)
        self._manpower_spin.setSingleStep(10000)
        lay.addRow(tr("state_dlg_manpower_label"), self._manpower_spin)

        self._impassable_check = QCheckBox(tr("state_dlg_impassable"))
        lay.addRow("", self._impassable_check)

        self._controller_combo = QComboBox()
        self._controller_combo.addItem(tr("state_dlg_controller_same"), "")
        for tag in self._country_tags:
            self._controller_combo.addItem(tag, tag)
        lay.addRow(tr("state_dlg_controller_label"), self._controller_combo)

        self._supplies_spin = QDoubleSpinBox()
        self._supplies_spin.setRange(0.0, 100.0)
        self._supplies_spin.setSingleStep(0.5)
        self._supplies_spin.setDecimals(2)
        lay.addRow(tr("state_dlg_supplies_label"), self._supplies_spin)

        # Victory-point city name fields; the primary name is required and the English name is optional.
        vp_box = QGroupBox(tr("state_dlg_vp_names"))
        vp_lay = QGridLayout(vp_box)
        vp_lay.addWidget(QLabel(tr("state_dlg_vp_province")), 0, 0)
        vp_lay.addWidget(QLabel(tr("state_dlg_vp_value")), 0, 1)
        vp_lay.addWidget(QLabel(tr("state_dlg_vp_city_name")), 0, 2)
        vp_lay.addWidget(QLabel(tr("state_dlg_vp_city_name_en")), 0, 3)
        self._vp_name_edits: dict[int, QLineEdit] = {}
        self._vp_name_en_edits: dict[int, QLineEdit] = {}
        self._vp_value_spins: dict[int, QSpinBox] = {}
        row_idx = 1
        vp_names_en = getattr(self._state, "vp_names_en", {}) or {}
        for vpid, vpval in self._state.victory_points.items():
            vp_lay.addWidget(QLabel(str(vpid)), row_idx, 0)
            value_spin = QSpinBox()
            # Keep existing projects with larger values intact while allowing
            # ample room for custom-map values as well as vanilla values.
            try:
                current_vp = max(0, int(vpval))
            except (TypeError, ValueError):
                current_vp = 0
            value_spin.setRange(0, max(1_000_000, current_vp))
            value_spin.setValue(current_vp)
            self._vp_value_spins[vpid] = value_spin
            vp_lay.addWidget(value_spin, row_idx, 1)
            edit = QLineEdit()
            edit.setPlaceholderText(self._state.name or f"State {self._state.id}")
            edit.setText(self._state.vp_names.get(vpid, ""))
            self._vp_name_edits[vpid] = edit
            vp_lay.addWidget(edit, row_idx, 2)
            edit_en = QLineEdit()
            edit_en.setPlaceholderText(f"State {self._state.id}")
            edit_en.setText(vp_names_en.get(vpid, ""))
            self._vp_name_en_edits[vpid] = edit_en
            vp_lay.addWidget(edit_en, row_idx, 3)
            row_idx += 1
        if not self._state.victory_points:
            vp_lay.addWidget(QLabel(tr("state_dlg_vp_none")), 1, 0, 1, 4)
        lay.addRow(vp_box)

        return w

    def _build_resources_tab(self) -> QWidget:
        w = QWidget()
        lay = QGridLayout(w)
        lay.setColumnStretch(0, 0)
        lay.setColumnStretch(1, 1)
        lay.addWidget(QLabel(f"<b>{tr('state_dlg_resources_hint')}</b>"), 0, 0, 1, 2)

        self._resource_spins: dict[str, QSpinBox] = {}
        for i, key in enumerate(RESOURCE_NAMES):
            lay.addWidget(QLabel(f"{tr(RESOURCE_LABELS[key])} ({key}):"), i + 1, 0)
            spin = QSpinBox()
            spin.setRange(0, 10000)
            lay.addWidget(spin, i + 1, 1)
            self._resource_spins[key] = spin
        lay.setRowStretch(len(RESOURCE_NAMES) + 1, 1)
        return w

    def _build_buildings_tab(self) -> QWidget:
        w = QWidget()
        lay = QGridLayout(w)
        lay.addWidget(
            QLabel(
                f"<b>{tr('state_dlg_buildings_hint')}</b><br>"
                f"<span style='color:#888'>{tr('state_dlg_buildings_sub')}</span>"
            ),
            0, 0, 1, 2,
        )
        self._building_spins: dict[str, QSpinBox] = {}
        for i, key in enumerate(STATE_BUILDINGS):
            lay.addWidget(QLabel(tr(BUILDING_LABELS.get(key, key)) + ":"), i + 1, 0)
            spin = QSpinBox()
            spin.setRange(0, BUILDING_MAX.get(key, 30))
            lay.addWidget(spin, i + 1, 1)
            self._building_spins[key] = spin

        # Provincial building entrance
        last_row = len(STATE_BUILDINGS) + 1
        lay.addWidget(QLabel(""), last_row, 0)  # blank line
        prov_btn = QPushButton(tr("state_dlg_edit_prov_buildings"))
        prov_btn.clicked.connect(self._on_edit_province_buildings)
        lay.addWidget(prov_btn, last_row + 1, 0, 1, 2)
        lay.setRowStretch(last_row + 2, 1)
        return w

    def _on_edit_province_buildings(self) -> None:
        """Opens the provincial building dialog box."""
        from features.map.state.province_buildings_dialog import (
            ProvinceBuildingsDialog,
        )
        # Use state.provinces as a list of all provinces (land has been filtered within the provinces)
        land_pids = list(self._state.provinces)
        dlg = ProvinceBuildingsDialog(self._state, land_pids, parent=self)
        dlg.exec_()

    def _build_cores_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        # extra core
        cores_box = QGroupBox(tr("state_dlg_cores_group"))
        cores_lay = QVBoxLayout(cores_box)
        self._cores_list = QListWidget()
        cores_lay.addWidget(self._cores_list)
        row = QHBoxLayout()
        add_core_btn = QPushButton(tr("state_dlg_add"))
        add_core_btn.clicked.connect(self._on_add_core)
        del_core_btn = QPushButton(tr("state_dlg_delete_selected"))
        del_core_btn.clicked.connect(self._on_del_core)
        row.addWidget(add_core_btn)
        row.addWidget(del_core_btn)
        cores_lay.addLayout(row)
        lay.addWidget(cores_box)

        # claim
        claims_box = QGroupBox(tr("state_dlg_claims_group"))
        claims_lay = QVBoxLayout(claims_box)
        self._claims_list = QListWidget()
        claims_lay.addWidget(self._claims_list)
        row2 = QHBoxLayout()
        add_claim_btn = QPushButton(tr("state_dlg_add"))
        add_claim_btn.clicked.connect(self._on_add_claim)
        del_claim_btn = QPushButton(tr("state_dlg_delete_selected"))
        del_claim_btn.clicked.connect(self._on_del_claim)
        row2.addWidget(add_claim_btn)
        row2.addWidget(del_claim_btn)
        claims_lay.addLayout(row2)
        lay.addWidget(claims_box)

        return w

    # ─────────── Load/Save ───────────

    def _load_from_state(self) -> None:
        s = self._state
        # If the old data name is in the form of key (STATE_123), the UI will display empty and let the user fill in the display name.
        display_name = s.name if (s.name and s.name != f"STATE_{s.id}") else ""
        self._name_edit.setText(display_name)
        self._name_en_edit.setText(getattr(s, "name_en", "") or "")
        self._manpower_spin.setValue(int(s.manpower or 0))
        self._impassable_check.setChecked(bool(getattr(s, "impassable", False)))

        ctl = getattr(s, "controller_tag", "") or ""
        idx = self._controller_combo.findData(ctl)
        self._controller_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self._supplies_spin.setValue(float(getattr(s, "local_supplies", 0.0) or 0.0))

        # Resources
        res = getattr(s, "resources", {}) or {}
        for key, spin in self._resource_spins.items():
            spin.setValue(int(res.get(key, 0) or 0))

        # architecture
        bld = getattr(s, "buildings", {}) or {}
        for key, spin in self._building_spins.items():
            spin.setValue(int(bld.get(key, 0) or 0))

        # core/claim
        self._cores_list.clear()
        for tag in getattr(s, "extra_cores", []) or []:
            self._cores_list.addItem(tag)
        self._claims_list.clear()
        for tag in getattr(s, "claims", []) or []:
            self._claims_list.addItem(tag)

    def _on_accept(self) -> None:
        s = self._state
        # Leave name blank (key will not be automatically filled in; press name_en or default "State {id}" when exporting)
        s.name = self._name_edit.text().strip()
        s.name_en = self._name_en_edit.text().strip()
        s.manpower = int(self._manpower_spin.value())
        s.impassable = bool(self._impassable_check.isChecked())
        s.controller_tag = self._controller_combo.currentData() or ""
        s.local_supplies = float(self._supplies_spin.value())

        s.resources = {
            k: int(spin.value())
            for k, spin in self._resource_spins.items()
            if int(spin.value()) > 0
        }
        s.buildings = {
            k: int(spin.value())
            for k, spin in self._building_spins.items()
            if int(spin.value()) > 0
        }
        s.extra_cores = [
            self._cores_list.item(i).text() for i in range(self._cores_list.count())
        ]
        s.claims = [
            self._claims_list.item(i).text() for i in range(self._claims_list.count())
        ]

        # Victory-point values and city name fields.
        edited_vps = {
            vpid: int(spin.value())
            for vpid, spin in self._vp_value_spins.items()
            if int(spin.value()) > 0
        }
        s.victory_points.clear()
        s.victory_points.update(edited_vps)

        # A zero value removes a VP, so remove its associated names as well.
        s.vp_names = {
            vpid: name for vpid, name in getattr(s, "vp_names", {}).items()
            if vpid in edited_vps
        }
        if not hasattr(s, "vp_names_en") or s.vp_names_en is None:
            s.vp_names_en = {}
        else:
            s.vp_names_en = {
                vpid: name for vpid, name in s.vp_names_en.items()
                if vpid in edited_vps
            }
        for vpid, edit in self._vp_name_edits.items():
            if vpid in edited_vps:
                s.vp_names[vpid] = edit.text().strip()
        for vpid, edit in self._vp_name_en_edits.items():
            if vpid in edited_vps:
                s.vp_names_en[vpid] = edit.text().strip()

        self.accept()

    # ─────────── Core / Claim Operation ───────────

    def _ask_tag(self, title: str) -> str:
        if self._country_tags:
            tag, ok = QInputDialog.getItem(
                self, title, tr("state_dlg_select_tag"), self._country_tags, 0, True
            )
        else:
            tag, ok = QInputDialog.getText(self, title, tr("state_dlg_input_tag"))
        return tag.strip().upper() if ok else ""

    def _on_add_core(self) -> None:
        tag = self._ask_tag(tr("state_dlg_add_core_title"))
        if not tag:
            return
        # Remove duplicates
        existing = [self._cores_list.item(i).text() for i in range(self._cores_list.count())]
        if tag in existing:
            return
        self._cores_list.addItem(tag)

    def _on_del_core(self) -> None:
        row = self._cores_list.currentRow()
        if row >= 0:
            self._cores_list.takeItem(row)

    def _on_add_claim(self) -> None:
        tag = self._ask_tag(tr("state_dlg_add_claim_title"))
        if not tag:
            return
        existing = [self._claims_list.item(i).text() for i in range(self._claims_list.count())]
        if tag in existing:
            return
        self._claims_list.addItem(tag)

    def _on_del_claim(self) -> None:
        row = self._claims_list.currentRow()
        if row >= 0:
            self._claims_list.takeItem(row)
