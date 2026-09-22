"""Export preflight dialog box—displays project completion and supports auto-completion and export.

This dialog box pops up when you click "Export MOD", listing the status of all required items:
  ✓ Completed / ✗ Missing (can be automatically completed) / ⚠ There is a problem
Users can choose "Autocomplete and export" or "Cancel"."""
from __future__ import annotations

import os
import traceback

import numpy as np
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFileDialog, QGroupBox, QCheckBox,
    QTextEdit, QMessageBox, QWidget, QComboBox, QScrollArea,
    QFrame, QGridLayout, QSizePolicy,
)

from data.constants import DEFAULT_MOD_OUTPUT_PATH, DEFAULT_MOD_NAME
from services.readiness_service import check_project_readiness
from ui.i18n import tr


_READINESS_TOOLTIP_KEYS = {
    "readiness.map_dimensions": "export_tip_readiness_map_dimensions",
    "readiness.provinces": "export_tip_readiness_provinces",
    "readiness.land": "export_tip_readiness_land",
    "readiness.states": "export_tip_readiness_states",
    "readiness.countries": "export_tip_readiness_countries",
    "readiness.strategic_regions": "export_tip_readiness_strategic_regions",
    "readiness.continents": "export_tip_readiness_continents",
    "readiness.terrain": "export_tip_readiness_terrain",
    "readiness.heightmap": "export_tip_readiness_heightmap",
    "readiness.assets": "export_tip_readiness_assets",
    "readiness.placements": "export_tip_readiness_placements",
}

_SCOPE_TOOLTIP_KEYS = {
    "map": "export_scope_map_tooltip",
    "states": "export_scope_states_tooltip",
    "countries": "export_scope_countries_tooltip",
    "strategic_regions": "export_scope_strategic_regions_tooltip",
    "localisation": "export_scope_localisation_tooltip",
    "supply": "export_scope_supply_tooltip",
    "gfx": "export_scope_gfx_tooltip",
    "replace_path": "export_scope_replace_path_tooltip",
    "descriptor": "export_scope_descriptor_tooltip",
    "compact_ids": "export_scope_compact_ids_tooltip",
}


# A preflight worker can outlive its dialog when the user closes during a
# large plan build.  Keep detached workers alive until QThread.finished so
# closing the modal dialog cannot destroy a running QThread.
_DETACHED_PREFLIGHT_WORKERS: set[QThread] = set()


def _detach_preflight_worker(worker: QThread) -> None:
    """Let a running preflight finish safely after its dialog closes."""
    _DETACHED_PREFLIGHT_WORKERS.add(worker)
    for signal in (
        worker.readiness_ready,
        worker.completed,
        worker.failed,
        worker.finished,
    ):
        try:
            signal.disconnect()
        except TypeError:
            pass
    worker.setParent(None)
    worker.finished.connect(worker.deleteLater)
    worker.finished.connect(
        lambda finished_worker=worker:
            _DETACHED_PREFLIGHT_WORKERS.discard(finished_worker)
    )


class _WrappedCheckOption(QWidget):
    """A checkable scope option whose long explanation can wrap cleanly."""

    def __init__(self, text: str, tooltip: str, checked: bool, parent=None) -> None:
        super().__init__(parent)
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        self.checkbox.setAccessibleName(text)
        self.checkbox.setToolTip(tooltip)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.PlainText)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        label.setToolTip(tooltip)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.checkbox, 0, Qt.AlignTop)
        layout.addWidget(label, 1)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.checkbox.setChecked(not self.checkbox.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)


# ── Inspection item data ────────────────────────────────────
# CheckItem / check_project_readiness has been moved to services/readiness_service.py:
# Completion is a business rule, and the export preflight and production progress panels must share the same set of standards.


# ── Auto-completion logic ─────────────────────────────────────

def auto_complete_project(project, canvas) -> list[str]:
    """Automatically complete missing data and return the completion operation log."""
    log: list[str] = []
    pm = canvas.province_map
    tm = canvas.tile_map
    province_count = int(pm.max())
    if province_count == 0:
        return [tr("export_auto_no_provinces")]

    # 1. Automatically generate State
    state_mgr = project.state_mgr
    if not state_mgr.states:
        state_mgr.auto_split(pm, tm, per_state=15)
        log.append(tr("export_auto_gen_states").format(count=len(state_mgr.states)))

    # 2. Automatically create countries
    country_mgr = project.country_mgr
    if not country_mgr.countries:
        country_mgr.create_country("AAA", name="Default Nation", color=(100, 100, 200))
        log.append(tr("export_auto_create_country"))

    # 3. Assign the unowned State to the first country
    first_tag = next(iter(country_mgr.countries))
    unowned = []
    for sid in state_mgr.states:
        if not country_mgr.get_owner_of_state(sid):
            unowned.append(sid)
    if unowned:
        for sid in unowned:
            country_mgr.assign_state(sid, first_tag)
            state = state_mgr.get_state(sid)
            if state:
                state.owner_tag = first_tag
        log.append(tr("export_auto_assign_states").format(
            count=len(unowned), tag=first_tag))

    # 4. Set up a capital city
    for tag, country in country_mgr.countries.items():
        if country.capital <= 0:
            owned_states = country_mgr.get_states_of_country(tag)
            if owned_states:
                first_state = state_mgr.get_state(owned_states[0])
                if first_state and first_state.provinces:
                    country.capital = first_state.provinces[0]
                    log.append(tr("export_auto_set_capital").format(
                        tag=tag, pid=country.capital))

    # 5. Automatically generate strategic areas
    sr_mgr = project.strategic_region_mgr
    if sr_mgr.count() == 0:
        sr_mgr.auto_generate(pm, tm, state_mgr=state_mgr)
        log.append(tr("export_auto_gen_sr").format(count=sr_mgr.count()))

    # 6. Mainland (at least one default)
    cont_mgr = project.continent_mgr
    if cont_mgr.count() == 0:
        cont_mgr.add_continent("default_continent")
        log.append(tr("export_auto_create_continent"))

    return log


# ── Background export thread ──────────────────────────────────────

class ExportWorker(QThread):
    """Execute export in the background to avoid interface freezing."""
    progress = pyqtSignal(str)       # progress text
    finished = pyqtSignal(object)    # Send ExportReport on success
    failed = pyqtSignal(str)         # Send error message on failure

    def __init__(
        self, output_dir: str, canvas, project,
        scope: dict[str, bool] | None = None, parent=None,
        profile_name: str = "legacy_full", repair_policy: str = "apply-safe",
        overwrite: bool = False, backup: bool = False,
    ) -> None:
        super().__init__(parent)
        self.output_dir = output_dir
        self.canvas = canvas
        self.project = project
        self.scope = scope or {}
        self.profile_name = profile_name or "legacy_full"
        self.repair_policy = repair_policy or "apply-safe"
        self.overwrite = bool(overwrite)
        self.backup = bool(backup)
        self.game_target = None
        self.profile = None
        self.dimensions = None
        self.plan = None
        self.plan_summary = ""
        self.export_result = None

    def run(self) -> None:
        try:
            self.progress.emit(tr("export_worker_pre_check"))
            from services.export_planner import format_plan_summary, plan_export_from_project
            from services.export_service import ExportReport, export_planned_mod
            from services.game_profile_service import load_profile_for_target
            from services.validation_service import report_from_findings

            self.game_target = self.project.resolve_game_target()
            self.profile = load_profile_for_target(self.game_target)
            map_height, map_width = self.canvas.province_map.shape[:2]
            self.dimensions = (int(map_width), int(map_height))
            self.plan = plan_export_from_project(
                self.project,
                self.canvas,
                profile_name=self.profile_name,
                game_target=self.game_target,
                game_profile=self.profile,
                repair_policy=self.repair_policy,
                scope=self.scope,
                dimensions=self.dimensions,
            )
            self.plan_summary = format_plan_summary(self.plan)
            self.progress.emit(self.plan_summary)
            self.export_result = export_planned_mod(
                self.plan,
                self.output_dir,
                overwrite=self.overwrite,
                backup=self.backup,
            )
            plan = self.plan
            stats = {
                "provinces": int(plan.snapshot.province_map.max()),
                "states": len(getattr(plan.snapshot.state_mgr, "states", {}) or {}),
                "countries": len(getattr(plan.snapshot.country_mgr, "countries", {}) or {}),
                "files": len(self.export_result.written_files),
            }
            try:
                plan_report = report_from_findings(plan.findings)
            except Exception:
                plan_report = None
            report = ExportReport(
                warnings=[note.message for note in plan.findings
                          if note.severity in ("warning", "error", "blocker")],
                fixed=["[%s] %s" % (repair.safety, repair.summary)
                       for repair in plan.applied_repairs],
                stats=stats,
                validation_report=plan_report,
            )
            self.finished.emit(report)
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class PreflightWorker(QThread):
    """Build the readiness list and export-plan preview off the GUI thread."""

    readiness_ready = pyqtSignal(object)
    completed = pyqtSignal(object, object, str)
    failed = pyqtSignal(str)

    def __init__(
        self, project, canvas, profile_name: str, repair_policy: str,
        scope: dict[str, bool], parent=None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.canvas = canvas
        self.profile_name = profile_name or "legacy_full"
        self.repair_policy = repair_policy or "apply-safe"
        self.scope = dict(scope or {})

    def run(self) -> None:
        try:
            from services.export_planner import format_plan_summary, plan_export_from_project
            from services.game_profile_service import load_profile_for_target

            game_target = self.project.resolve_game_target()
            profile = load_profile_for_target(game_target)
            map_height, map_width = self.canvas.province_map.shape[:2]
            dimensions = (int(map_width), int(map_height))
            items = check_project_readiness(
                self.project,
                self.canvas,
                profile=profile,
                dimensions=dimensions,
                profile_name=self.profile_name,
            )
            self.readiness_ready.emit(items)
            if self.isInterruptionRequested():
                return

            plan = plan_export_from_project(
                self.project,
                self.canvas,
                profile_name=self.profile_name,
                game_target=game_target,
                game_profile=profile,
                repair_policy=self.repair_policy,
                scope=self.scope,
                dimensions=dimensions,
            )
            self.completed.emit(items, plan, format_plan_summary(plan))
        except Exception as exc:
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")


class ExportDialog(QDialog):
    """Export preflight dialog - Check → Autocomplete → Select Directory → Export."""

    def __init__(self, project, canvas, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.canvas = canvas
        self._worker: ExportWorker | None = None
        self._preflight_worker: PreflightWorker | None = None
        self._preflight_request = 0
        self._preflight_pending = False
        self._closing = False
        self._items = []
        self._plan = None

        self.setWindowTitle(tr("export_dlg_title"))
        self.setMinimumSize(520, 360)
        self.resize(880, 620)
        self.setSizeGripEnabled(True)
        self._check_timer = QTimer(self)
        self._check_timer.setSingleShot(True)
        self._check_timer.setInterval(180)
        self._check_timer.timeout.connect(self._run_check)
        self._build_ui()
        # Let Qt paint the compact shell before checking large maps or cloning
        # managers for the plan preview.
        QTimer.singleShot(0, self._run_check)

    # ── UI construction ──

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Keep the action bar visible while the content itself can be shorter
        # than the form on small screens or at high display scaling.
        self._content_scroll = QScrollArea()
        self._content_scroll.setWidgetResizable(True)
        self._content_scroll.setFrameShape(QFrame.NoFrame)
        self._content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._content_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 8, 2)
        content_layout.setSpacing(8)
        self._content_scroll.setWidget(content)
        root.addWidget(self._content_scroll, 1)

        # Title
        title = QLabel(tr("export_pre_check_title"))
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        title.setToolTip(tr("export_pre_check_tooltip"))
        content_layout.addWidget(title)

        # Check results area
        self._check_group = QGroupBox(tr("export_project_readiness"))
        self._check_group.setToolTip(tr("export_readiness_tooltip"))
        check_group_layout = QVBoxLayout(self._check_group)
        check_group_layout.setContentsMargins(6, 6, 6, 6)
        self._readiness_notice = QLabel()
        self._readiness_notice.setWordWrap(True)
        self._readiness_notice.setStyleSheet(
            "color: #f59e0b; font-weight: bold; padding: 2px 4px;"
        )
        self._readiness_notice.setVisible(False)
        self._readiness_notice.setToolTip(tr("export_readiness_tooltip"))
        check_group_layout.addWidget(self._readiness_notice)
        self._check_widget = QWidget()
        self._check_layout = QVBoxLayout(self._check_widget)
        self._check_layout.setContentsMargins(4, 4, 4, 4)
        self._check_layout.setSpacing(4)
        self._warning_rows = []
        self._check_scroll = QScrollArea()
        self._check_scroll.setWidgetResizable(True)
        self._check_scroll.setFrameShape(QFrame.NoFrame)
        self._check_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._check_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._check_scroll.setMinimumHeight(140)
        self._check_scroll.setMaximumHeight(220)
        self._check_scroll.setWidget(self._check_widget)
        self._check_scroll.verticalScrollBar().rangeChanged.connect(
            lambda _minimum, _maximum: self._update_warning_notice()
        )
        check_group_layout.addWidget(self._check_scroll)
        content_layout.addWidget(self._check_group)

        # Export range selection
        scope_group = QGroupBox(tr("export_scope"))
        scope_group.setToolTip(tr("export_scope_tooltip"))
        scope_layout = QVBoxLayout(scope_group)
        scope_layout.setContentsMargins(8, 8, 8, 8)
        scope_layout.setSpacing(6)

        # Default button row: Select All / Map Only / Clear
        preset_row = QHBoxLayout()
        for preset_key, label_key in (
            ("all", "export_scope_btn_select_all"),
            ("map_only", "export_scope_btn_map_only"),
            ("none", "export_scope_btn_clear"),
        ):
            btn = QPushButton(tr(label_key))
            btn.setStyleSheet(
                "QPushButton { padding: 4px 12px; border-radius: 3px; }"
            )
            btn.setToolTip(tr(f"export_scope_preset_{preset_key}_tooltip"))
            btn.clicked.connect(
                lambda _checked=False, p=preset_key: self._apply_scope_preset(p)
            )
            preset_row.addWidget(btn)
        preset_row.addStretch()
        scope_layout.addLayout(preset_row)

        self._scope_checks = {}
        scope_items = [
            ("map", tr("export_scope_map"), True),
            ("states", tr("export_scope_states"), True),
            ("countries", tr("export_scope_countries"), True),
            ("strategic_regions", tr("export_scope_strategic_regions"), True),
            ("localisation", tr("export_scope_localisation"), True),
            ("supply", tr("export_scope_supply"), True),
            ("gfx", tr("export_scope_gfx"), True),
            ("replace_path", tr("export_scope_replace_path"), True),
            ("descriptor", tr("export_scope_descriptor"), True),
            ("compact_ids", tr("export_scope_compact_ids"), True),
        ]
        scope_grid = QGridLayout()
        scope_grid.setHorizontalSpacing(18)
        scope_grid.setVerticalSpacing(2)
        scope_grid.setColumnStretch(0, 1)
        scope_grid.setColumnStretch(1, 1)
        self._scope_options = {}
        for key, label, default in scope_items:
            tooltip = tr(_SCOPE_TOOLTIP_KEYS[key])
            option = _WrappedCheckOption(label, tooltip, default)
            cb = option.checkbox
            cb.stateChanged.connect(lambda _state: self._schedule_check())
            self._scope_checks[key] = cb
            self._scope_options[key] = option
            index = len(self._scope_checks) - 1
            scope_grid.addWidget(option, index // 2, index % 2)
        scope_layout.addLayout(scope_grid)
        content_layout.addWidget(scope_group)

        # Export profile selection (M2.5/M2.6: planner profile plus repair policy)
        profile_group = QGroupBox(tr("export_profile_group"))
        profile_group.setToolTip(tr("export_profile_tooltip"))
        profile_layout = QGridLayout(profile_group)
        profile_layout.setHorizontalSpacing(8)
        profile_layout.setVerticalSpacing(6)
        self._profile_combo = QComboBox()
        self._profile_combo.addItems(["legacy_full", "foundation", "acceptance", "scaffold"])
        self._profile_combo.setCurrentText("legacy_full")
        self._profile_combo.currentTextChanged.connect(self._on_profile_changed)
        self._profile_combo.setToolTip(tr("export_profile_combo_tooltip"))
        profile_layout.addWidget(QLabel(tr("export_profile_label")), 0, 0)
        profile_layout.addWidget(self._profile_combo, 0, 1)
        self._repair_combo = QComboBox()
        self._repair_combo.addItems(["apply-safe", "propose", "off"])
        self._repair_combo.setCurrentText("apply-safe")
        self._repair_combo.setToolTip(tr("export_repair_tooltip"))
        self._repair_combo.currentTextChanged.connect(lambda _text: self._schedule_check())
        profile_layout.addWidget(QLabel(tr("export_repair_label")), 0, 2)
        profile_layout.addWidget(self._repair_combo, 0, 3)
        self._overwrite_check = QCheckBox(tr("export_overwrite"))
        self._overwrite_check.setChecked(False)
        self._overwrite_check.setToolTip(tr("export_overwrite_tooltip"))
        profile_layout.addWidget(self._overwrite_check, 1, 0, 1, 2)
        self._backup_check = QCheckBox(tr("export_backup"))
        self._backup_check.setChecked(False)
        self._backup_check.setToolTip(tr("export_backup_tooltip"))
        profile_layout.addWidget(self._backup_check, 1, 2, 1, 2)
        profile_layout.setColumnStretch(1, 1)
        profile_layout.setColumnStretch(3, 1)
        content_layout.addWidget(profile_group)

        profile_help = QLabel(
            tr("export_profile_help_short")
        )
        profile_help.setWordWrap(True)
        profile_help.setStyleSheet("color: #9aa0ab; font-size: 12px; padding: 2px 4px;")
        profile_help.setToolTip(tr("export_profile_help"))
        content_layout.addWidget(profile_help)

        plan_group = QGroupBox(tr("export_plan"))
        plan_group.setToolTip(tr("export_plan_tooltip"))
        plan_layout = QVBoxLayout(plan_group)
        plan_layout.setContentsMargins(6, 6, 6, 6)
        self._plan_label = QTextEdit()
        self._plan_label.setReadOnly(True)
        self._plan_label.setMinimumHeight(48)
        self._plan_label.setMaximumHeight(125)
        self._plan_label.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._plan_label.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._plan_label.setPlaceholderText(tr("export_plan_loading"))
        self._plan_label.setToolTip(tr("export_plan_tooltip"))
        plan_layout.addWidget(self._plan_label)
        content_layout.addWidget(plan_group)


        # Log area (initially hidden)
        self._log_box = QGroupBox(tr("export_log"))
        self._log_box.setToolTip(tr("export_log_tooltip"))
        log_layout = QVBoxLayout(self._log_box)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(150)
        self._log_text.setToolTip(tr("export_log_tooltip"))
        log_layout.addWidget(self._log_text)
        self._log_box.setVisible(False)
        content_layout.addWidget(self._log_box)

        # Progress bar (initially hidden)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # indeterminate
        self._progress_bar.setVisible(False)
        content_layout.addWidget(self._progress_bar)

        self._progress_label = QLabel("")
        self._progress_label.setVisible(False)
        self._progress_label.setWordWrap(True)
        content_layout.addWidget(self._progress_label)

        # button row
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_auto = QPushButton(tr("export_btn_auto"))
        self._btn_auto.setStyleSheet(
            "QPushButton { background: #4f8cff; color: white; padding: 8px 20px;"
            " border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #6ba1ff; }"
            "QPushButton:disabled { background: #444; color: #888; }"
        )
        self._btn_auto.clicked.connect(self._on_auto_export)
        btn_layout.addWidget(self._btn_auto)
        self._btn_auto.setToolTip(tr("export_auto_tooltip"))

        self._btn_export_direct = QPushButton(tr("export_btn_direct"))
        self._btn_export_direct.setStyleSheet(
            "QPushButton { background: #22c55e; color: white; padding: 8px 20px;"
            " border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #2ad66a; }"
            "QPushButton:disabled { background: #444; color: #888; }"
        )
        self._btn_export_direct.clicked.connect(self._on_direct_export)
        btn_layout.addWidget(self._btn_export_direct)
        self._btn_export_direct.setToolTip(tr("export_direct_tooltip"))

        self._btn_cancel = QPushButton(tr("btn_cancel"))
        self._btn_cancel.setStyleSheet(
            "QPushButton { padding: 8px 16px; border-radius: 4px; }"
        )
        self._btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_cancel.setToolTip(tr("export_cancel_tooltip"))
        root.addLayout(btn_layout)

    # ── Check ──

    def _schedule_check(self) -> None:
        """Debounce option changes so presets do not start many plans at once."""
        self._check_timer.start()

    def _clear_check_rows(self) -> None:
        while self._check_layout.count():
            child = self._check_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_preflight_loading(self) -> None:
        self._clear_check_rows()
        loading = QLabel(tr("export_preflight_loading"))
        loading.setWordWrap(True)
        loading.setStyleSheet("color: #9aa0ab; padding: 8px;")
        loading.setToolTip(tr("export_preflight_tooltip"))
        self._check_layout.addWidget(loading)
        self._items = []
        self._warning_rows = []
        self._has_missing = False
        self._has_blocking = False
        self._plan = None
        self._readiness_notice.setVisible(False)
        self._plan_label.setPlainText(tr("export_plan_loading"))
        self._plan_label.setToolTip(tr("export_plan_tooltip"))
        self._btn_auto.setEnabled(False)
        self._btn_export_direct.setEnabled(False)

    def _readiness_tooltip(self, item) -> str:
        suggestion_key = _READINESS_TOOLTIP_KEYS.get(
            str(getattr(item, "code", "") or "")
        )
        suggestion = tr(suggestion_key) if suggestion_key else tr(
            "export_tip_readiness_default"
        )
        state = tr("export_tip_readiness_ok") if item.status == "ok" else tr(
            "export_tip_readiness_action"
        )
        return f"{item.name}\n\n{item.detail}\n\n{state} {suggestion}"

    def _update_warning_notice(self) -> None:
        """Keep a warning count and overflow cue outside the readiness scroll."""
        warning_count = sum(
            1 for item in self._items if item.status == "warning"
        )
        if warning_count == 0:
            self._readiness_notice.clear()
            self._readiness_notice.setVisible(False)
            return

        viewport_height = self._check_scroll.viewport().height()
        if viewport_height <= 0:
            self._readiness_notice.setText(
                tr("export_readiness_warnings_scrolling").format(count=warning_count)
            )
            self._readiness_notice.setVisible(True)
            return

        visible_warnings = 0
        used_height = 0
        row_spacing = max(0, self._check_layout.spacing())
        for row in self._warning_rows:
            row_height = max(row.sizeHint().height(), row.minimumSizeHint().height())
            next_height = used_height + (row_spacing if visible_warnings else 0) + row_height
            if visible_warnings and next_height > viewport_height:
                break
            used_height = next_height
            visible_warnings += 1

        more = warning_count - visible_warnings
        if more > 0:
            text = tr("export_readiness_warnings_more").format(
                count=warning_count, more=more
            )
        else:
            text = tr("export_readiness_warnings_all").format(count=warning_count)
        self._readiness_notice.setText(text)
        self._readiness_notice.setVisible(True)

    def _render_readiness(self, items) -> None:
        self._clear_check_rows()
        # Keep warnings at the top while retaining the original order inside
        # each status group, so important rows are visible before the fold.
        status_order = {"warning": 0, "missing": 1, "ok": 2}
        self._items = sorted(
            list(items or []),
            key=lambda item: status_order.get(item.status, 1),
        )
        self._warning_rows = []
        self._has_missing = False
        self._has_blocking = False

        for item in self._items:
            row = QHBoxLayout()
            row.setSpacing(6)
            tooltip = self._readiness_tooltip(item)

            # status icon
            if item.status == "ok":
                icon = "✓"
                color = "#22c55e"
            elif item.status == "warning":
                icon = "⚠"
                color = "#f59e0b"
            else:
                icon = "✗"
                color = "#ef4444"
                self._has_missing = True
                if not item.can_auto:
                    self._has_blocking = True

            icon_label = QLabel(icon)
            icon_label.setStyleSheet(
                f"color: {color}; font-size: 16px; font-weight: bold;"
            )
            icon_label.setFixedWidth(24)
            icon_label.setToolTip(tooltip)
            row.addWidget(icon_label)

            # name + details
            text = f"<b>{item.name}</b> — {item.detail}"
            if item.can_auto and item.status != "ok":
                text += f' <span style="color: #4f8cff;">[{tr("export_can_auto")}]</span>'
            info = QLabel(text)
            info.setWordWrap(True)
            info.setTextFormat(Qt.RichText)
            info.setToolTip(tooltip)
            row.addWidget(info, 1)

            container = QWidget()
            container.setLayout(row)
            container.setToolTip(tooltip)
            self._check_layout.addWidget(container)
            if item.status == "warning":
                self._warning_rows.append(container)

        self._check_widget.adjustSize()
        self._update_warning_notice()
        QTimer.singleShot(0, self._update_warning_notice)

    def _start_preflight(self) -> None:
        """Start one coalesced readiness/plan request for current options."""
        self._preflight_request += 1
        request_id = self._preflight_request
        current = self._preflight_worker
        if current is not None and current.isRunning():
            self._preflight_pending = True
            current.requestInterruption()
            self._set_preflight_loading()
            return

        self._preflight_pending = False
        self._set_preflight_loading()
        scope = {key: cb.isChecked() for key, cb in self._scope_checks.items()}
        worker = PreflightWorker(
            self.project,
            self.canvas,
            profile_name=str(self._profile_combo.currentText()),
            repair_policy=str(self._repair_combo.currentText()),
            scope=scope,
            parent=self,
        )
        self._preflight_worker = worker
        worker.readiness_ready.connect(
            lambda items, rid=request_id: self._on_preflight_readiness(rid, items)
        )
        worker.completed.connect(
            lambda items, plan, summary, rid=request_id:
                self._on_preflight_completed(rid, items, plan, summary)
        )
        worker.failed.connect(
            lambda message, rid=request_id: self._on_preflight_failed(rid, message)
        )
        worker.finished.connect(lambda w=worker: self._on_preflight_thread_finished(w))
        worker.start()

    def _run_check(self) -> None:
        """Queue readiness and plan work without blocking the dialog shell."""
        self._start_preflight()

    def _on_preflight_readiness(self, request_id: int, items) -> None:
        if request_id != self._preflight_request or self._closing:
            return
        self._render_readiness(items)

    def _on_preflight_completed(self, request_id: int, items, plan, summary: str) -> None:
        if request_id != self._preflight_request or self._closing:
            return
        if not self._items:
            self._render_readiness(items)
        self._plan = plan
        self._plan_label.setPlainText(summary)
        self._plan_label.setToolTip(
            tr("export_plan_tooltip")
            + ("\n\n" + "\n".join(str(blocker) for blocker in plan.blockers)
               if getattr(plan, "blockers", None) else "")
        )

        blocked = self._has_blocking or bool(getattr(plan, "blocked", False))
        self._btn_auto.setText(
            tr("export_btn_auto") if self._has_missing else tr("export_btn_export")
        )
        self._btn_export_direct.setVisible(self._has_missing)
        self._btn_auto.setEnabled(not blocked)
        self._btn_export_direct.setEnabled(not blocked and self._has_missing)

    def _on_preflight_failed(self, request_id: int, error_msg: str) -> None:
        if request_id != self._preflight_request or self._closing:
            return
        self._clear_check_rows()
        error = QLabel(tr("export_preflight_failed").format(error=error_msg))
        error.setWordWrap(True)
        error.setStyleSheet("color: #ef4444; padding: 8px;")
        error.setToolTip(error_msg)
        self._check_layout.addWidget(error)
        self._plan_label.setPlainText(tr("export_plan_unavailable"))
        self._btn_auto.setEnabled(False)
        self._btn_export_direct.setEnabled(False)

    def _on_preflight_thread_finished(self, worker: PreflightWorker) -> None:
        if self._preflight_worker is not worker:
            return
        pending = self._preflight_pending and not self._closing
        self._preflight_worker = None
        worker.deleteLater()
        if self._closing:
            # Closing may have been requested while the worker was still
            # building a plan.  Finish the modal close only after the thread
            # has stopped, so the dialog never destroys a live QThread.
            super().reject()
            return
        if pending:
            self._preflight_pending = False
            self._start_preflight()

    # ── Default ──

    # "Map only" scope key is checked by default - only generate pure map files in the map/ directory
    # (BMP + definition.csv + buildings + adjacencies + strategicregions + supply_nodes/railways)
    # Do not write states/countries/localisation/gfx/replace_path/descriptor —
    # Suitable for users who already have a MOD framework and only need map materials
    # compact_ids are also retained: only map export also requires definition.csv numbers to be consecutive
    _MAP_ONLY_KEYS = frozenset({"map", "strategic_regions", "supply", "compact_ids"})

    def _apply_scope_preset(self, preset: str) -> None:
        """Set scope check status with one click. preset = "all" | "map_only" | "none"."""
        for key, cb in self._scope_checks.items():
            if preset == "all":
                cb.setChecked(True)
            elif preset == "none":
                cb.setChecked(False)
            elif preset == "map_only":
                cb.setChecked(key in self._MAP_ONLY_KEYS)

    def _on_profile_changed(self, profile_name: str) -> None:
        """Keep the visible layer selection valid for the selected profile."""
        foundation = str(profile_name) == "foundation"
        for key in ("countries", "localisation", "gfx"):
            check = self._scope_checks.get(key)
            if check is None:
                continue
            if foundation:
                check.setChecked(False)
            option = self._scope_options.get(key)
            if option is not None:
                option.setEnabled(not foundation)
            else:
                check.setEnabled(not foundation)
        self._schedule_check()

    def _refresh_plan_summary(self) -> None:
        """Compatibility hook for callers that request a refreshed preview."""
        self._schedule_check()


    # ── Export action ──

    def _on_auto_export(self) -> None:
        """Export with planner-approved safe repairs on the export snapshot."""
        if self._repair_combo.currentText() != "apply-safe":
            self._repair_combo.setCurrentText("apply-safe")
        self._log_box.setVisible(True)
        self._log_text.setPlainText(
            "Planner safe repairs will be applied to the export snapshot; the live project is unchanged."
        )
        self._do_export()

    def _on_direct_export(self) -> None:
        """Export directly without completion."""
        # warning
        missing = [i for i in self._items if i.status == "missing"]
        if missing:
            names = tr("export_separator").join(i.name for i in missing)
            reply = QMessageBox.warning(
                self, tr("dlg_confirm"),
                tr("export_confirm_skip").format(names=names),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._do_export()

    def _do_export(self) -> None:
        """Select Directory → Start background export."""
        # Compaction is turned off and there are holes in the numbering → The exported MOD attributes will be misaligned and must be confirmed by the user
        if not self._scope_checks["compact_ids"].isChecked():
            ids = np.unique(self.canvas.province_map)
            nonzero = ids[ids > 0]
            gaps = int(nonzero[-1]) - len(nonzero) if len(nonzero) else 0
            if gaps > 0:
                reply = QMessageBox.warning(
                    self, tr("dlg_confirm"),
                    tr("export_compact_off_warn").format(gaps=gaps),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        output_dir = QFileDialog.getExistingDirectory(
            self, tr("export_choose_dir"), DEFAULT_MOD_OUTPUT_PATH)
        if not output_dir:
            return

        # Disable button, show progress
        self._btn_auto.setEnabled(False)
        self._btn_export_direct.setEnabled(False)
        self._btn_cancel.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_label.setVisible(True)
        self._progress_label.setText(tr("export_exporting"))

        self._output_dir = output_dir
        scope = {k: cb.isChecked() for k, cb in self._scope_checks.items()}
        self._worker = ExportWorker(output_dir, self.canvas, self.project,
                                    scope=scope, parent=self,
                                    profile_name=str(self._profile_combo.currentText()),
                                    repair_policy=str(self._repair_combo.currentText()),
                                    overwrite=self._overwrite_check.isChecked(),
                                    backup=self._backup_check.isChecked())
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_export_done)
        self._worker.failed.connect(self._on_export_failed)
        self._worker.start()

    def _on_progress(self, text: str) -> None:
        self._progress_label.setText(text)

    def _on_export_done(self, report) -> None:
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)

        # Run MOD verification once as the shared report (M3.2c3).
        from export.verify_mod import ModVerifier
        worker = self._worker
        validation_report = ModVerifier.verify_report(
            self._output_dir,
            profile=getattr(worker, "profile", None),
            expected_dimensions=getattr(worker, "dimensions", None),
            game_target=getattr(worker, "game_target", None),
        )
        verify_errors = [finding.message for finding in validation_report.errors]
        verify_warnings = [finding.message for finding in validation_report.warnings]

        # Build result text
        lines = [tr("export_result_success").format(path=self._output_dir)]
        if report.stats:
            lines.append(tr("export_result_stats_header"))
            stat_labels = {
                "provinces": tr("export_stat_provinces"),
                "states": tr("export_stat_states"),
                "countries": tr("export_stat_countries"),
                "files": tr("export_stat_files"),
            }
            for k, v in report.stats.items():
                lines.append(f"  {stat_labels.get(k, k)}: {v}")
        if report.fixed:
            lines.append(tr("export_result_fixed_header"))
            for f in report.fixed:
                lines.append(f"  [{tr('export_result_fixed_tag')}] {f}")
        if report.warnings:
            lines.append(tr("export_result_warnings_header"))
            for w in report.warnings:
                lines.append(f"  [{tr('export_result_warning_tag')}] {w}")

        # Add verification results
        if not verify_errors and not verify_warnings:
            lines.append(tr("export_verify_header"))
            lines.append(tr("export_verify_all_pass"))
        else:
            if verify_errors:
                lines.append(tr("export_verify_errors_header").format(
                    count=len(verify_errors)))
                for e in verify_errors:
                    lines.append(f"  ❌ {e}")
            if verify_warnings:
                lines.append(tr("export_verify_warnings_header").format(
                    count=len(verify_warnings)))
                for w in verify_warnings:
                    lines.append(f"  ⚠ {w}")

        # Show detailed results dialog
        self._show_export_result(lines, verify_errors)

    def _show_export_result(
        self, lines: list[str], verify_errors: list[str]
    ) -> None:
        """Display export results and validation reports with scrollable dialog boxes."""
        dlg = QDialog(self)
        dlg.setWindowTitle(
            tr("export_result_title_errors") if verify_errors
            else tr("export_result_title_ok")
        )
        dlg.setMinimumSize(560, 380)
        dlg.resize(760, 620)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        result_scroll = QScrollArea()
        result_scroll.setWidgetResizable(True)
        result_scroll.setFrameShape(QFrame.NoFrame)
        result_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        result_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        result_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        result_content = QWidget()
        layout = QVBoxLayout(result_content)
        layout.setContentsMargins(2, 2, 8, 2)
        layout.setSpacing(8)
        result_scroll.setWidget(result_content)
        root.addWidget(result_scroll, 1)

        # title tag
        if verify_errors:
            header = QLabel(tr("export_done_has_errors"))
            header.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #ef4444;"
            )
        else:
            header = QLabel(tr("export_done_all_pass"))
            header.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #22c55e;"
            )
        layout.addWidget(header)

        # Scrollable text area
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText("\n".join(lines))
        text_edit.setMinimumHeight(170)
        text_edit.setMaximumHeight(300)
        text_edit.setToolTip(tr("export_result_report_tooltip"))
        layout.addWidget(text_edit)

        # Foundation-freeze workflow (M8): reachable from foundation exports only.
        # Non-foundation exports show an informational note instead so they do
        # not falsely claim freeze support. Safe: widget uses explicit paths
        # and the backend service only; export semantics are unchanged.
        try:
            from views.foundation_workflow import (
                FoundationWorkflowWidget,
                is_foundation_profile,
            )

            _profile_name = ""
            try:
                _combo = getattr(self, "_profile_combo", None)
                if _combo is not None:
                    _profile_name = str(_combo.currentText())
            except Exception:
                _profile_name = ""
            if not _profile_name:
                try:
                    _profile_name = str(
                        getattr(getattr(self, "_worker", None), "profile_name", "")
                        or ""
                    )
                except Exception:
                    _profile_name = ""
            _artifact_dir = ""
            try:
                _artifact_dir = str(getattr(self, "_output_dir", "") or "")
            except Exception:
                _artifact_dir = ""
            if is_foundation_profile(_profile_name):
                _workflow = FoundationWorkflowWidget(
                    artifact_dir=_artifact_dir, parent=dlg
                )
                layout.addWidget(_workflow)
            else:
                _freeze_note = QLabel(
                    "Foundation freeze workflow is available only for "
                    "foundation-profile exports."
                )
                _freeze_note.setWordWrap(True)
                layout.addWidget(_freeze_note)
        except Exception:
            pass

        # close button
        btn_close = QPushButton(tr("export_result_close"))
        btn_close.setStyleSheet(
            "QPushButton { padding: 8px 20px; border-radius: 4px;"
            " font-weight: bold; }"
        )
        btn_close.clicked.connect(dlg.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        root.addLayout(btn_layout)

        dlg.exec_()
        self.accept()

    def _on_export_failed(self, error_msg: str) -> None:
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)
        self._btn_auto.setEnabled(True)
        self._btn_export_direct.setEnabled(True)
        self._btn_cancel.setEnabled(True)

        QMessageBox.critical(self, tr("export_failed_title"), error_msg)

    def _stop_preflight(self) -> None:
        """Request preflight cancellation without blocking the GUI thread.

        The plan builder is cooperative but may be inside a large, non-
        interruptible operation when the user closes this dialog.  Waiting
        here blocks Qt's event loop for the remainder of that operation and
        makes the application appear hung.  Detach the worker and close the
        modal dialog immediately; the worker is retained until QThread.finish
        arrives so its parent cannot destroy a live thread.
        """
        self._closing = True
        self._preflight_request += 1
        self._preflight_pending = False
        self._check_timer.stop()
        worker = self._preflight_worker
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            # QDialog.exec_() keeps the application modal until the dialog
            # itself closes, so detaching is required to close immediately
            # without destroying a running QThread.
            _detach_preflight_worker(worker)
            self._preflight_worker = None
            return

        # The thread has already stopped; clean it up before destroying the
        # dialog.  The finished signal may still be queued, so clear our
        # reference to make that callback harmless.
        self._preflight_worker = None
        worker.deleteLater()

    def reject(self) -> None:
        self._stop_preflight()
        super().reject()

    def closeEvent(self, event) -> None:
        self._stop_preflight()
        event.accept()
