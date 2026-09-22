"""Placement review page (M5.2/M5.3 UI slice) — standalone QWidget.

Standalone review surface for authored map placement records. The page
owns no domain state and performs no filesystem, export, or domain
mutations: it renders duck-typed slot/port records, edits an explicit
land-to-sea mapping, and forwards user intent through signals so a
PlacementController can be wired up later.
"""

import re
from numbers import Integral

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QComboBox,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QScrollArea,
)

from ui.i18n import tr
from ui.styles import (
    make_section as _make_section,
    _COMBOBOX_STYLE,
    _DIM_LABEL_STYLE,
    _LABEL_STYLE,
    _LIST_STYLE,
    _PRIMARY_BTN_STYLE,
    _SECONDARY_BTN_STYLE,
)

__all__ = ["PlacementPage", "parse_sea_mapping"]

_PAIR_SPLIT_RE = re.compile(r"[,\r\n;]+")
_INT_RE = re.compile(r"[+-]?\d+")
_SEP_RE = re.compile(r"(?P<left>[^:=]+)[:=](?P<right>[^:=]+)")
_MAX_DIAGNOSTIC_LINES = 5
_MISSING = object()
_TRANSFORM_DECIMALS = 6
_TRANSFORM_MINIMUM = -1000000.0
_TRANSFORM_MAXIMUM = 1000000.0


def parse_sea_mapping(text):
    """Parse an explicit land-province to sea-province mapping.

    Pairs are separated by commas, semicolons, or newlines and use a
    ``:`` or ``=`` separator, e.g. ``"12:34, 56:78"``. Empty fragments
    from trailing separators or blank lines are ignored. Anything else
    must be a well-formed pair: both ids must be positive integers and
    each land id may appear only once. The page never guesses a sea.

    Raises ValueError on blank input, malformed pairs,
    non-positive/non-integer ids, duplicate land ids, or non-text input.
    """
    if not isinstance(text, str):
        raise ValueError(
            "sea mapping must be text, got {}".format(type(text).__name__)
        )
    if not text.strip():
        raise ValueError("sea mapping is blank; enter explicit land:sea pairs")
    mapping = {}
    for chunk in _PAIR_SPLIT_RE.split(text):
        token = chunk.strip()
        if not token:
            continue
        match = _SEP_RE.fullmatch(token)
        if match is None:
            raise ValueError("malformed sea mapping pair: {!r}".format(token))
        land_raw = match.group("left").strip()
        sea_raw = match.group("right").strip()
        if _INT_RE.fullmatch(land_raw) is None:
            raise ValueError("malformed sea mapping pair: {!r}".format(token))
        if _INT_RE.fullmatch(sea_raw) is None:
            raise ValueError("malformed sea mapping pair: {!r}".format(token))
        land = int(land_raw)
        sea = int(sea_raw)
        if land <= 0 or sea <= 0:
            raise ValueError(
                "province ids must be positive integers: {!r}".format(token)
            )
        if land in mapping:
            raise ValueError(
                "duplicate land province in sea mapping: {}".format(land)
            )
        mapping[land] = sea
    if not mapping:
        raise ValueError("sea mapping is blank; enter explicit land:sea pairs")
    return mapping


def _field(record, name, default=None):
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _coerce_province_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return int(value) if value > 0 else None
    if isinstance(value, str):
        token = value.strip()
        if _INT_RE.fullmatch(token) is not None:
            try:
                number = int(token)
            except ValueError:
                return None
            return number if number > 0 else None
    return None


def _coerce_slot_index(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, str):
        token = value.strip()
        if _INT_RE.fullmatch(token) is not None:
            try:
                return int(token)
            except ValueError:
                return None
    return None


def _fmt_num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return "{:g}".format(number)


def _extra_tags(record):
    tags = []
    for name in ("review_status", "provenance"):
        value = _field(record, name)
        if value:
            tags.append(str(value))
    return tags


def _slot_text(province_id, slot, record):
    parts = ["Slot {}#{}".format(province_id, slot)]
    meaning = _field(record, "meaning")
    if meaning:
        parts.append(str(meaning))
    x = _field(record, "x")
    y = _field(record, "y")
    if x is not None and y is not None:
        parts.append("@ ({}, {})".format(_fmt_num(x), _fmt_num(y)))
    tags = _extra_tags(record)
    if tags:
        parts.append("[{}]".format("/".join(tags)))
    return " ".join(parts)


def _port_text(province_id, record):
    sea = _coerce_province_id(_field(record, "sea_province"))
    parts = ["Port {} -> sea {}".format(province_id, sea if sea is not None else "-")]
    x = _field(record, "x")
    y = _field(record, "y")
    if x is not None and y is not None:
        parts.append("@ ({}, {})".format(_fmt_num(x), _fmt_num(y)))
    tags = _extra_tags(record)
    if tags:
        parts.append("[{}]".format("/".join(tags)))
    return " ".join(parts)


class PlacementPage(QWidget):
    """Standalone placement review page; no controller dependency."""

    generate_slots_requested = pyqtSignal()
    generate_ports_requested = pyqtSignal(object)
    accept_selected_requested = pyqtSignal(object, object, str)
    refresh_requested = pyqtSignal()
    placement_selection_filter_changed = pyqtSignal(str)
    placement_urban_overlay_toggled = pyqtSignal(bool)
    placement_vp_names_toggled = pyqtSignal(bool)
    transform_update_requested = pyqtSignal(str, object, float, float, float, float)
    transform_reset_requested = pyqtSignal(str, object)

    parse_sea_mapping = staticmethod(parse_sea_mapping)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        tip = QLabel(tr("placement_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet(_DIM_LABEL_STYLE)
        lay.addWidget(tip)

        map_box = _make_section(tr("placement_map_section"))
        map_layout = map_box.layout()

        map_guide = QLabel(tr("placement_map_guide"))
        map_guide.setWordWrap(True)
        map_guide.setTextFormat(Qt.RichText)
        map_guide.setStyleSheet(_DIM_LABEL_STYLE)
        map_layout.addWidget(map_guide)

        selection_row = QHBoxLayout()
        selection_label = QLabel(tr("placement_selection_label"))
        selection_label.setStyleSheet(_LABEL_STYLE)
        selection_row.addWidget(selection_label)
        self._selection_filter_combo = QComboBox()
        self._selection_filter_combo.setStyleSheet(_COMBOBOX_STYLE)
        self._selection_filter_combo.addItem(
            tr("placement_selection_all"), "all"
        )
        self._selection_filter_combo.addItem(
            tr("placement_selection_buildings"), "building"
        )
        self._selection_filter_combo.addItem(
            tr("placement_selection_ports"), "port"
        )
        self._selection_filter_combo.addItem(
            tr("placement_selection_victory_points"), "vp"
        )
        self._selection_filter_combo.currentIndexChanged.connect(
            self._on_selection_filter_changed
        )
        selection_row.addWidget(self._selection_filter_combo, 1)
        map_layout.addLayout(selection_row)

        selection_help = QLabel(tr("placement_selection_help"))
        selection_help.setWordWrap(True)
        selection_help.setStyleSheet(_DIM_LABEL_STYLE)
        map_layout.addWidget(selection_help)

        self._urban_overlay_chk = QCheckBox(tr("placement_show_urban"))
        self._urban_overlay_chk.setToolTip(tr("placement_show_urban_tip"))
        self._urban_overlay_chk.toggled.connect(
            self.placement_urban_overlay_toggled.emit
        )
        map_layout.addWidget(self._urban_overlay_chk)

        self._vp_names_chk = QCheckBox(tr("placement_show_vp_names"))
        self._vp_names_chk.setToolTip(tr("placement_show_vp_names_tip"))
        self._vp_names_chk.toggled.connect(
            self.placement_vp_names_toggled.emit
        )
        map_layout.addWidget(self._vp_names_chk)

        urban_help = QLabel(tr("placement_map_backdrop_help"))
        urban_help.setWordWrap(True)
        urban_help.setStyleSheet(_DIM_LABEL_STYLE)
        map_layout.addWidget(urban_help)
        lay.addWidget(map_box)

        generate_box = _make_section(tr("placement_generate_section"))
        gl = generate_box.layout()

        self._generate_slots_btn = QPushButton(tr("placement_generate_slots_btn"))
        self._generate_slots_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._generate_slots_btn.clicked.connect(self._on_generate_slots)
        gl.addWidget(self._generate_slots_btn)

        mapping_lbl = QLabel(tr("placement_mapping_label"))
        mapping_lbl.setStyleSheet(_LABEL_STYLE)
        gl.addWidget(mapping_lbl)

        self._mapping_edit = QPlainTextEdit()
        self._mapping_edit.setPlaceholderText(tr("placement_mapping_hint"))
        self._mapping_edit.setMinimumHeight(64)
        self._mapping_edit.setMaximumHeight(110)
        self._mapping_edit.setStyleSheet(
            "QPlainTextEdit { background: #1f2126; border: 1px solid #2c2f36;"
            " border-radius: 4px; color: #e8eaed; font-size: 13px; }"
        )
        gl.addWidget(self._mapping_edit)

        mapping_help = QLabel(tr("placement_mapping_help"))
        mapping_help.setWordWrap(True)
        mapping_help.setStyleSheet(_DIM_LABEL_STYLE)
        gl.addWidget(mapping_help)

        self._generate_ports_btn = QPushButton(tr("placement_generate_ports_btn"))
        self._generate_ports_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._generate_ports_btn.clicked.connect(self._on_generate_ports)
        gl.addWidget(self._generate_ports_btn)

        self._replace_generated_check = QCheckBox(
            tr("placement_replace_generated_label")
        )
        self._replace_generated_check.setChecked(False)
        self._replace_generated_check.setToolTip(
            tr("placement_replace_generated_help")
        )
        gl.addWidget(self._replace_generated_check)

        replace_help = QLabel(tr("placement_replace_generated_help"))
        replace_help.setWordWrap(True)
        replace_help.setStyleSheet(_DIM_LABEL_STYLE)
        gl.addWidget(replace_help)
        lay.addWidget(generate_box)

        records_box = _make_section(tr("placement_records_section"))
        rl = records_box.layout()

        self._records_summary = QLabel(tr("placement_records_empty"))
        self._records_summary.setStyleSheet(_DIM_LABEL_STYLE)
        rl.addWidget(self._records_summary)

        self._records_list = QListWidget()
        self._records_list.setStyleSheet(_LIST_STYLE)
        self._records_list.setUniformItemSizes(True)
        self._records_list.setMinimumHeight(180)
        rl.addWidget(self._records_list)
        lay.addWidget(records_box)

        review_box = _make_section(tr("placement_review_section"))
        vl = review_box.layout()

        status_row = QHBoxLayout()
        review_lbl = QLabel(tr("placement_review_status_label"))
        review_lbl.setStyleSheet(_LABEL_STYLE)
        status_row.addWidget(review_lbl)
        self._review_combo = QComboBox()
        self._review_combo.setStyleSheet(_COMBOBOX_STYLE)
        self._review_combo.addItem(tr("placement_reviewed"), "reviewed")
        self._review_combo.addItem(tr("placement_accepted"), "accepted")
        status_row.addWidget(self._review_combo)
        status_row.addStretch(1)
        vl.addLayout(status_row)

        self._accept_btn = QPushButton(tr("placement_accept_selected_btn"))
        self._accept_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._accept_btn.clicked.connect(self._on_accept_selected)
        vl.addWidget(self._accept_btn)

        self._refresh_btn = QPushButton(tr("placement_refresh_btn"))
        self._refresh_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._refresh_btn.clicked.connect(self._on_refresh)
        vl.addWidget(self._refresh_btn)
        lay.addWidget(review_box)

        transform_box = _make_section(tr("placement_transform_section"))
        transform_layout = transform_box.layout()
        self._transform_label = QLabel(tr("placement_transform_none"))
        self._transform_label.setWordWrap(True)
        self._transform_label.setStyleSheet(_DIM_LABEL_STYLE)
        transform_layout.addWidget(self._transform_label)
        transform_form = QFormLayout()
        self._transform_x_spin = QDoubleSpinBox()
        self._transform_x_spin.setDecimals(_TRANSFORM_DECIMALS)
        self._transform_x_spin.setRange(_TRANSFORM_MINIMUM, _TRANSFORM_MAXIMUM)
        self._transform_x_spin.setSingleStep(0.1)
        transform_form.addRow("X", self._transform_x_spin)
        self._transform_y_spin = QDoubleSpinBox()
        self._transform_y_spin.setDecimals(_TRANSFORM_DECIMALS)
        self._transform_y_spin.setRange(_TRANSFORM_MINIMUM, _TRANSFORM_MAXIMUM)
        self._transform_y_spin.setSingleStep(0.1)
        transform_form.addRow("Y", self._transform_y_spin)
        self._transform_rotation_spin = QDoubleSpinBox()
        self._transform_rotation_spin.setDecimals(_TRANSFORM_DECIMALS)
        self._transform_rotation_spin.setRange(_TRANSFORM_MINIMUM, _TRANSFORM_MAXIMUM)
        self._transform_rotation_spin.setSingleStep(0.1)
        transform_form.addRow("Rotation", self._transform_rotation_spin)
        self._transform_height_spin = QDoubleSpinBox()
        self._transform_height_spin.setDecimals(_TRANSFORM_DECIMALS)
        self._transform_height_spin.setRange(_TRANSFORM_MINIMUM, _TRANSFORM_MAXIMUM)
        self._transform_height_spin.setSingleStep(0.1)
        transform_form.addRow("Height", self._transform_height_spin)
        transform_layout.addLayout(transform_form)
        transform_buttons = QHBoxLayout()
        self._transform_apply_btn = QPushButton(tr("placement_transform_apply_btn"))
        self._transform_apply_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._transform_apply_btn.clicked.connect(self._on_transform_apply)
        transform_buttons.addWidget(self._transform_apply_btn)
        self._transform_reset_btn = QPushButton(tr("placement_transform_reset_btn"))
        self._transform_reset_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._transform_reset_btn.clicked.connect(self._on_transform_reset)
        transform_buttons.addWidget(self._transform_reset_btn)
        transform_layout.addLayout(transform_buttons)
        lay.addWidget(transform_box)
        self._transform_kind = None
        self._transform_key = None
        self._transform_has_selection = False
        self._set_transform_enabled(False)

        diag_box = _make_section(tr("placement_diagnostics_section"))
        dl = diag_box.layout()
        self._diag_label = QLabel(tr("placement_diagnostics_none"))
        self._diag_label.setWordWrap(True)
        self._diag_label.setStyleSheet(_DIM_LABEL_STYLE)
        dl.addWidget(self._diag_label)
        lay.addWidget(diag_box)

        self._status_label = QLabel(tr("placement_status_ready"))
        self._status_label.setStyleSheet("color: #4f8cff; font-size: 11px;")
        lay.addWidget(self._status_label)

        lay.addStretch(1)
        scroll.setWidget(page)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def mapping_text(self):
        return self._mapping_edit.toPlainText()

    def set_mapping_text(self, text):
        self._mapping_edit.setPlainText(text or "")

    def review_status(self):
        return self._review_combo.currentData() or "reviewed"

    def replace_generated(self):
        return bool(self._replace_generated_check.isChecked())

    def set_replace_generated(self, on):
        self._replace_generated_check.setChecked(bool(on))

    def placement_selection_filter(self):
        return self._selection_filter_combo.currentData() or "all"

    def set_placement_selection_filter(self, value):
        target = str(value or "all")
        for index in range(self._selection_filter_combo.count()):
            if self._selection_filter_combo.itemData(index) == target:
                self._selection_filter_combo.setCurrentIndex(index)
                return

    def show_urban_overlay(self):
        return bool(self._urban_overlay_chk.isChecked())

    def set_show_urban_overlay(self, on):
        self._urban_overlay_chk.setChecked(bool(on))

    def show_victory_point_names(self):
        return bool(self._vp_names_chk.isChecked())

    def set_show_victory_point_names(self, on):
        self._vp_names_chk.setChecked(bool(on))

    def set_generation_busy(self, busy):
        """Disable generation inputs while the main window runs a proposal."""
        enabled = not bool(busy)
        for widget in (
            self._generate_slots_btn,
            self._generate_ports_btn,
            self._mapping_edit,
            self._replace_generated_check,
        ):
            widget.setEnabled(enabled)

    def set_records(self, records):
        slots = []
        ports = []
        for record in records or []:
            province_id = _coerce_province_id(_field(record, "province_id"))
            if province_id is None:
                continue
            slot = _field(record, "slot", _MISSING)
            sea_province = _field(record, "sea_province", _MISSING)
            if slot is not _MISSING:
                slot_index = _coerce_slot_index(slot)
                if slot_index is None:
                    continue
                slots.append((province_id, slot_index, record))
            elif sea_province is not _MISSING:
                ports.append((province_id, record))
            else:
                # Buildings/weather and other placement record types are not
                # reviewable by this slot/port surface yet. Do not render
                # them as ports merely because they share province_id.
                continue
        slots.sort(key=lambda entry: (entry[0], entry[1]))
        ports.sort(key=lambda entry: entry[0])

        # Refresh calls are also made when the placement mode becomes visible.
        # Keep the already-built list when the displayed fields are unchanged;
        # rebuilding tens of thousands of QListWidgetItems is needlessly costly.
        signature = tuple(
            [
                (
                    "slot",
                    province_id,
                    slot_index,
                    _field(record, "meaning"),
                    _field(record, "x"),
                    _field(record, "y"),
                    _field(record, "provenance"),
                    _field(record, "review_status"),
                )
                for province_id, slot_index, record in slots
            ]
            + [
                (
                    "port",
                    province_id,
                    _field(record, "sea_province"),
                    _field(record, "x"),
                    _field(record, "y"),
                    _field(record, "provenance"),
                    _field(record, "review_status"),
                )
                for province_id, record in ports
            ]
        )
        if signature == getattr(self, "_records_signature", None):
            return
        self._records_signature = signature

        self._records_list.setUpdatesEnabled(False)
        try:
            self._records_list.clear()
            for province_id, slot_index, record in slots:
                item = QListWidgetItem(_slot_text(province_id, slot_index, record))
                item.setData(Qt.UserRole, ("slot", (province_id, slot_index)))
                self._track_checkable(item)
                self._records_list.addItem(item)
            for province_id, record in ports:
                item = QListWidgetItem(_port_text(province_id, record))
                item.setData(Qt.UserRole, ("port", province_id))
                self._track_checkable(item)
                self._records_list.addItem(item)
        finally:
            self._records_list.setUpdatesEnabled(True)
            self._records_list.viewport().update()
        if self._records_list.count() == 0:
            self._records_summary.setText(tr("placement_records_empty"))
        else:
            self._records_summary.setText(
                tr("placement_records_summary", len(slots), len(ports))
            )

    def selected_records(self):
        slot_keys = []
        port_ids = []
        for row in range(self._records_list.count()):
            item = self._records_list.item(row)
            if item.checkState() != Qt.Checked:
                continue
            data = item.data(Qt.UserRole)
            if not isinstance(data, tuple) or len(data) != 2:
                continue
            kind, payload = data
            if kind == "slot":
                try:
                    province_id, slot_index = payload
                except (TypeError, ValueError):
                    continue
                slot_keys.append((int(province_id), int(slot_index)))
            elif kind == "port":
                port_ids.append(int(payload))
        return slot_keys, port_ids

    def set_diagnostics(self, diagnostics):
        items = list(diagnostics or [])
        if not items:
            self._diag_label.setText(tr("placement_diagnostics_none"))
            return
        lines = [tr("placement_diagnostics_summary", len(items))]
        for entry in items[:_MAX_DIAGNOSTIC_LINES]:
            lines.append(self._diagnostic_line(entry))
        if len(items) > _MAX_DIAGNOSTIC_LINES:
            lines.append("...")
        self._diag_label.setText("\n".join(lines))

    def set_transform_selection(self, kind, key, x, y, rotation, height):
        self._transform_kind = kind
        self._transform_key = key
        self._transform_has_selection = True
        self._transform_x_spin.setValue(float(x))
        self._transform_y_spin.setValue(float(y))
        self._transform_rotation_spin.setValue(float(rotation))
        self._transform_height_spin.setValue(float(height))
        self._transform_label.setText(tr("placement_transform_selected", kind, key))
        self._set_transform_enabled(True)

    def set_victory_point_selection(self, province_id, value=None, name=""):
        """Show a selected VP as read-only state data in the transform panel."""
        try:
            pid = int(province_id)
        except (TypeError, ValueError):
            pid = province_id
        try:
            value_text = str(int(value)) if value is not None else "?"
        except (TypeError, ValueError):
            value_text = str(value) if value is not None else "?"
        name_text = ""
        if isinstance(name, str) and name.strip():
            name_text = ", name " + name.strip()
        self._transform_kind = "vp"
        self._transform_key = pid
        self._transform_has_selection = False
        self._transform_x_spin.setValue(0.0)
        self._transform_y_spin.setValue(0.0)
        self._transform_rotation_spin.setValue(0.0)
        self._transform_height_spin.setValue(0.0)
        self._transform_label.setText(
            tr("placement_transform_vp_selected", pid, value_text, name_text)
        )
        self._set_transform_enabled(False)

    def clear_transform_selection(self):
        self._transform_kind = None
        self._transform_key = None
        self._transform_has_selection = False
        self._transform_x_spin.setValue(0.0)
        self._transform_y_spin.setValue(0.0)
        self._transform_rotation_spin.setValue(0.0)
        self._transform_height_spin.setValue(0.0)
        self._transform_label.setText(tr("placement_transform_none"))
        self._set_transform_enabled(False)

    def selected_transform(self):
        if not self._transform_has_selection:
            return None
        return (
            self._transform_kind,
            self._transform_key,
            float(self._transform_x_spin.value()),
            float(self._transform_y_spin.value()),
            float(self._transform_rotation_spin.value()),
            float(self._transform_height_spin.value()),
        )

    def _set_transform_enabled(self, enabled):
        self._transform_x_spin.setEnabled(enabled)
        self._transform_y_spin.setEnabled(enabled)
        self._transform_rotation_spin.setEnabled(enabled)
        self._transform_height_spin.setEnabled(enabled)
        self._transform_apply_btn.setEnabled(enabled)
        self._transform_reset_btn.setEnabled(enabled)

    def set_status(self, text):
        self._status_label.setText(text or "")

    @staticmethod
    def _track_checkable(item):
        item.setFlags((item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
        item.setCheckState(Qt.Unchecked)

    @staticmethod
    def _diagnostic_line(entry):
        code = _field(entry, "code", None) or "issue"
        message = _field(entry, "message", None)
        province_id = _coerce_province_id(_field(entry, "province_id", None))
        head = "[{}]".format(code)
        if province_id is not None:
            head += " P{}".format(province_id)
        if message:
            return "{}: {}".format(head, message)
        return head

    def _on_generate_slots(self):
        self.set_status(tr("placement_slots_requested"))
        self.generate_slots_requested.emit()

    def _on_generate_ports(self):
        try:
            mapping = parse_sea_mapping(self._mapping_edit.toPlainText())
        except ValueError as exc:
            self.set_status("{} {}".format(tr("placement_error_invalid_mapping"), exc))
            return
        self.set_status(tr("placement_ports_requested", len(mapping)))
        self.generate_ports_requested.emit(mapping)

    def _on_accept_selected(self):
        slot_keys, port_ids = self.selected_records()
        status = self.review_status()
        if not slot_keys and not port_ids:
            self.set_status(tr("placement_accept_empty"))
        else:
            self.set_status(
                tr("placement_accept_requested", len(slot_keys), len(port_ids), status)
            )
        self.accept_selected_requested.emit(slot_keys, port_ids, status)

    def _on_refresh(self):
        self.refresh_requested.emit()

    def _on_selection_filter_changed(self, index):
        value = self._selection_filter_combo.itemData(index) or "all"
        self.placement_selection_filter_changed.emit(str(value))

    def _on_transform_apply(self):
        selection = self.selected_transform()
        if selection is None:
            self.set_status(tr("placement_transform_empty"))
            return
        selected_kind = selection[0]
        selected_key = selection[1]
        selected_x = float(selection[2])
        selected_y = float(selection[3])
        selected_rotation = float(selection[4])
        selected_height = float(selection[5])
        self.set_status(tr("placement_transform_applied", selected_kind, selected_key))
        self.transform_update_requested.emit(selected_kind, selected_key, selected_x, selected_y, selected_rotation, selected_height)

    def _on_transform_reset(self):
        selection = self.selected_transform()
        if selection is None:
            self.set_status(tr("placement_transform_empty"))
            return
        selected_kind = selection[0]
        selected_key = selection[1]
        self.set_status(tr("placement_transform_reset_requested", selected_kind, selected_key))
        self.transform_reset_requested.emit(selected_kind, selected_key)
